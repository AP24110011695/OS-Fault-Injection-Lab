# Learning Notes: Filesystems, Mounts, tmpfs & ENOSPC

## 1. Overview & Context

In the OS Fault Injection Lab, **Phase 12** models one of the most common production failures: a disk filling up until the OS starts returning `ENOSPC` ("no space left on device"). A size-capped **tmpfs** is mounted inside the container and a writer process fills it exactly the way a leaking service fills a real disk — chunk by chunk — while the monitor watches filesystem usage climb past the threshold.

---

## 2. Filesystems, Mount Points and tmpfs

Linux composes the directory tree from **filesystems** attached at **mount points**. `mount -t tmpfs -o size=16m tmpfs /tmp/fault_disk` attaches a fresh, empty filesystem at that directory; everything inside it lives in RAM (and swap, here disabled by the container's config) and **vanishes on unmount**.

That is what makes disk-fault injection safe:

- The fault is **size-capped** by the kernel (`size=16m`) — the writer physically cannot consume more than 16MB, so the container (and the host) is never at risk.
- The fault is **disposable** — `umount` erases the entire filesystem; no file deletion bookkeeping is even needed for correctness.
- The fault is **isolated** — writes inside the tmpfs never touch the container's normal filesystem. The lab proves this (see §5).

The writer is started **only after** `/proc/mounts` confirms the path is really a tmpfs mountpoint with the expected size cap. `/proc/mounts` is the kernel's own table — one line per mount with device, mount point, filesystem type, and options (`rw,relatime,size=16384k`). Trusting anything else (e.g., "the directory exists") would risk writing onto the real filesystem.

---

## 3. ENOSPC and How a Service Fails

When the filesystem is exhausted, the kernel returns `ENOSPC` (errno 28) from `write()`/`open()`. The lab's writer treats it the way a real leaking service behaves: it **keeps running and retrying**, still failing on every attempt. The disk stays at 100% until recovery intervenes.

One observed detail worth knowing: near the full mark, a 1MB `write()` may **partially succeed** — the kernel writes what still fits and the file ends up smaller than requested. One trial's recovery deleted 39 files where ~16 full blocks were expected: the tail of the fill produced short writes. Recovery deletes *everything* in the mount, so the count is honest either way.

---

## 4. Why MTTD Includes the Fill Time

Detection threshold is `DISK_THRESHOLD_PERCENT` (90%) sustained for `CONSECUTIVE_POLLS_THRESHOLD` (3) polls at 0.5s. The writer adds 1MB every 0.05s, so the tmpfs reaches 90% of 16MB in ~0.72s. MTTD is therefore:

$$\text{MTTD} \approx \underbrace{t_{\text{fill to 90\%}}}_{\approx 0.72s} + \underbrace{3 \times T_{\text{poll}}}_{\text{debounce} \approx 1.0-1.5s} \approx 1.8s - 2.2s$$

This is the same shape as the memory_pressure fault: the OS does not signal "disk getting full" the way it signals a process death — the monitor must **watch a resource climb** into the danger zone, so detection necessarily includes the ramp-up time. A faster writer would lower MTTD but make the fault less realistic; a slower one raises MTTD.

Observed across 15 trials: MTTD mean 1.947s (min 1.767s, max 2.166s) — matching the theory almost exactly.

---

## 5. Observed Numbers and Leak Proof

15 trials, 100% recovery success:

| Metric | Mean | Median | Min | Max |
|---|---|---|---|---|
| MTTD (sec) | 1.947 | 1.920 | 1.767 | 2.166 |
| MTTR (sec) | 1.957 | 1.930 | 1.776 | 2.175 |

Recovery overhead (MTTR − MTTD) is only ~0.010s: once the writer is killed and its files deleted, the tmpfs drops to 0.0% instantly.

Leak proof after the full run:

- **0 leftover mounts** — after every trial the runner umounts, removes the directory, and re-reads `/proc/mounts` to confirm the path is gone; the run ends with a hard assertion.
- **Container root filesystem unchanged** — `df`-equivalent (`psutil.disk_usage("/")`) before the trials: 33,619,210,240 bytes used; after: 33,619,251,200; delta **+40,960 bytes (~0.0001%)** — runtime noise from container bookkeeping, none of the ~16MB of fault data, which lived and died inside the size-capped tmpfs.

---

## 6. `df` vs `du`

Two tools, two questions:

- **`df` (disk free)** asks the *filesystem* how much space is used — what `psutil.disk_usage()` reads. Deleted-but-open files still count here (space is freed only when the last fd closes).
- **`du` (disk usage)** walks the *directory tree* and sums file sizes — it cannot see space held by unlinked-but-open files.

This gap is a classic production mystery ("`du` says 2GB, `df` says 100GB used"): a process deleted its logs but holds the file descriptors open. The lab's recovery kills the writer **before** deleting files precisely so the two views converge and the usage-drop verification is trustworthy.
