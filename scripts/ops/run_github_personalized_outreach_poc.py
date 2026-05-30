#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from job_hunt_copilot.ai_outreach_poc import (  # noqa: E402
    GithubPersonalizedOutreachPocRequest,
    run_github_personalized_outreach_poc,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--contact-name", required=True)
    parser.add_argument("--contact-company")
    parser.add_argument("--contact-role")
    parser.add_argument("--email")
    parser.add_argument("--linkedin-url")
    parser.add_argument("--sender-background-summary", required=True)
    parser.add_argument("--availability-window", required=True)
    parser.add_argument("--min-confidence-score", type=int, default=70)
    parser.add_argument("--model")
    args = parser.parse_args()

    request = GithubPersonalizedOutreachPocRequest(
        contact_name=args.contact_name,
        contact_company=args.contact_company,
        contact_role=args.contact_role,
        sender_background_summary=args.sender_background_summary,
        availability_window=args.availability_window,
        linkedin_url=args.linkedin_url,
        email=args.email,
        min_confidence_score=args.min_confidence_score,
        model=args.model,
    )
    result = run_github_personalized_outreach_poc(
        request,
        project_root=Path(args.project_root),
    )
    print(json.dumps(result.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
