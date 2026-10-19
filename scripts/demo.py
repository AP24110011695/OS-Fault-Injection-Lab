import argparse
import sys
from pathlib import Path

# Ensure project root is in sys.path when executed directly as a script
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from experiment.runner import run_all_experiments


def main() -> None:
    parser = argparse.ArgumentParser(description="OS Fault Injection Lab Interactive Demonstration")
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="Number of trials per fault type for the demo (default: 1)",
    )
    args = parser.parse_args()

    print("==================================================")
    print("  OS Fault Injection Lab — Interactive Demo")
    print("==================================================")
    print(f"Executing demonstration run with {args.trials} trial(s) per fault type.\n")

    run_all_experiments(trial_count=args.trials)

    print("\n==================================================")
    print("  Demo completed successfully!")
    print("  Results saved to results/results.csv")
    print("  Publication charts saved to results/*.png")
    print("==================================================")


if __name__ == "__main__":
    main()
