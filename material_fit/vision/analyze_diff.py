from __future__ import annotations

import argparse
import json
from pathlib import Path

from .diff_analysis import ImageDiffConfig, analyze_image_diff
from .screen_capture import DEFAULT_CAPTURE_DIR, DEFAULT_PREFIX, find_latest_candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze Unity/Laya material screenshot differences")
    parser.add_argument("--reference", required=True, help="Unity reference image path")
    parser.add_argument(
        "--candidate",
        default="latest",
        help="Laya candidate image path, or 'latest' to use the newest laya_candidate_XX.png",
    )
    parser.add_argument(
        "--candidate-dir",
        default=str(DEFAULT_CAPTURE_DIR),
        help="Directory used when --candidate latest",
    )
    parser.add_argument("--candidate-prefix", default=DEFAULT_PREFIX, help="Filename prefix used when --candidate latest")
    parser.add_argument("--mask", default="", help="Optional mask image path")
    parser.add_argument("--output-dir", required=True, help="Directory for diff image and JSON report")
    parser.add_argument("--no-diff-image", action="store_true", help="Skip visual diff PNG generation")
    args = parser.parse_args()

    candidate_path = _resolve_candidate(args.candidate, args.candidate_dir, args.candidate_prefix)

    result = analyze_image_diff(
        ImageDiffConfig(
            reference_path=args.reference,
            candidate_path=candidate_path,
            mask_path=args.mask or None,
            output_dir=args.output_dir,
            generate_diff_image=not args.no_diff_image,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 2


def _resolve_candidate(candidate: str, candidate_dir: str, candidate_prefix: str) -> str:
    if candidate.lower() != "latest":
        return candidate
    latest = find_latest_candidate(candidate_dir, candidate_prefix)
    if not latest:
        raise FileNotFoundError(
            f"No candidate image found in {candidate_dir!r}. "
            f"Expected {candidate_prefix}_XX.png, or legacy {candidate_prefix}.png."
        )
    return str(latest)


if __name__ == "__main__":
    raise SystemExit(main())