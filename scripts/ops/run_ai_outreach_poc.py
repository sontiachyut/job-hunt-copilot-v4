#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from job_hunt_copilot.ai_outreach_poc import AiOutreachPocRequest, run_ai_outreach_poc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--jd-path", required=True)
    parser.add_argument("--resume-path", required=True)
    parser.add_argument("--company-name")
    parser.add_argument("--role-title")
    parser.add_argument("--contact-name")
    parser.add_argument("--contact-role")
    parser.add_argument("--send-to-email")
    parser.add_argument("--model")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--no-attach-resume", action="store_true")
    parser.add_argument("--no-attach-jd", action="store_true")
    parser.add_argument("--subject-prefix", default="[AI POC] ")
    args = parser.parse_args()

    request = AiOutreachPocRequest(
        jd_path=args.jd_path,
        resume_path=args.resume_path,
        company_name=args.company_name,
        role_title=args.role_title,
        contact_name=args.contact_name,
        contact_role=args.contact_role,
        send_to_email=args.send_to_email,
        model=args.model,
        send=args.send,
        attach_resume=not args.no_attach_resume,
        attach_jd=not args.no_attach_jd,
        subject_prefix=args.subject_prefix,
    )
    result = run_ai_outreach_poc(
        request,
        project_root=Path(args.project_root),
    )
    print(json.dumps(result.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
