from __future__ import annotations

import re
from pathlib import Path

import pytest

from job_hunt_copilot.paths import ProjectPaths


REPO_ROOT = Path(__file__).resolve().parents[1]
SECTION_RE = re.compile(r"^\s*\\section\{([^}]+)\}", re.MULTILINE)
STEP_FILENAMES = [
    ("tailoring_step_01_path", "step-01-jd-sections.yaml"),
    ("tailoring_step_02_path", "step-02-signals-raw.yaml"),
    ("tailoring_step_03_path", "step-03-signals-classified.yaml"),
    ("tailoring_step_04_path", "step-04-theme-scores.yaml"),
    ("tailoring_step_05_path", "step-05-theme-decision.yaml"),
    ("tailoring_step_06_path", "step-06-project-scores.yaml"),
    ("tailoring_step_07_path", "step-07-project-selection.yaml"),
    ("tailoring_step_08_path", "step-08-experience-evidence.yaml"),
    ("tailoring_step_09_path", "step-09-project-evidence.yaml"),
    ("tailoring_step_10_path", "step-10-gap-analysis.yaml"),
    ("tailoring_step_11_path", "step-11-bullet-allocation.yaml"),
    ("tailoring_step_12_path", "step-12-summary.yaml"),
    ("tailoring_step_13_path", "step-13-skills.yaml"),
    ("tailoring_step_14_path", "step-14-tech-stacks.yaml"),
    ("tailoring_step_15_path", "step-15-assembly.yaml"),
    ("tailoring_step_16_path", "step-16-verification.yaml"),
]


def _section_order(path: Path) -> list[str]:
    return SECTION_RE.findall(path.read_text(encoding="utf-8"))


def test_base_templates_follow_spec_section_order() -> None:
    projects_first = (
        REPO_ROOT / "assets" / "resume-tailoring" / "base" / "projects-first" / "base-resume.tex"
    )
    experience_first = (
        REPO_ROOT / "assets" / "resume-tailoring" / "base" / "experience-first" / "base-resume.tex"
    )

    assert _section_order(projects_first) == [
        "SUMMARY",
        "EDUCATION",
        "PROJECTS",
        "EXPERIENCE",
        "LEADERSHIP AND AWARDS",
        "TECHNICAL SKILLS",
    ]
    assert _section_order(experience_first) == [
        "SUMMARY",
        "EDUCATION",
        "EXPERIENCE",
        "PROJECTS",
        "AWARDS AND LEADERSHIP",
        "TECHNICAL SKILLS",
    ]


@pytest.mark.parametrize(
    ("template_type", "relative_path"),
    [
        ("A", Path("assets/resume-tailoring/base/projects-first/base-resume.tex")),
        ("B", Path("assets/resume-tailoring/base/experience-first/base-resume.tex")),
    ],
)
def test_base_resume_template_path_resolves_canonical_templates(
    template_type: str,
    relative_path: Path,
) -> None:
    paths = ProjectPaths.from_root(REPO_ROOT)

    assert paths.base_resume_template_path(template_type) == REPO_ROOT / relative_path


def test_base_resume_template_path_rejects_unknown_template() -> None:
    paths = ProjectPaths.from_root(REPO_ROOT)

    with pytest.raises(ValueError, match="Unknown base resume template type"):
        paths.base_resume_template_path("C")


def test_tailoring_step_paths_cover_the_new_pipeline_artifacts(tmp_path) -> None:
    project_root = tmp_path / "repo"
    paths = ProjectPaths.from_root(project_root)
    intelligence_dir = paths.tailoring_intelligence_dir("Acme Data Systems", "Software Engineer")

    for method_name, filename in STEP_FILENAMES:
        resolved = getattr(paths, method_name)("Acme Data Systems", "Software Engineer")
        assert resolved == intelligence_dir / filename
