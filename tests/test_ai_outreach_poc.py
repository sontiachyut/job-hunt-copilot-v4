from __future__ import annotations

import json
import subprocess
from pathlib import Path

from job_hunt_copilot.ai_outreach_poc import (
    AiOutreachPocRequest,
    GithubProfileResearch,
    GithubProfileResolver,
    GithubProfileResolutionRequest,
    GithubProfileResolutionResult,
    GithubProfileResearcher,
    GithubCoffeeChatDraftRequest,
    GithubCoffeeChatDraftResult,
    GithubPersonalizedOutreachPocRequest,
    GithubProjectAnalysisResult,
    GithubProjectAnalysisRequest,
    GithubProjectSelectionRequest,
    GithubProjectSelectionResult,
    GithubRepoCandidate,
    generate_github_coffee_chat_draft,
    build_ai_outreach_codex_exec_command,
    generate_github_project_analysis,
    generate_github_project_selection,
    generate_ai_outreach_draft,
    run_github_personalized_outreach_poc,
    send_ai_outreach_draft,
)


def _write_sender_profile(project_root: Path) -> None:
    profile_path = project_root / "assets" / "resume-tailoring" / "profile.md"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "# Achyutaram Sonti — Master Profile",
                "",
                "## Personal",
                "",
                "- **Name:** Achyutaram Sonti",
                "- **Email:** asonti1@asu.edu",
                "- **Phone:** 602-768-6071",
                "- **LinkedIn:** https://www.linkedin.com/in/asonti/",
                "- **GitHub:** https://github.com/sontiachyut",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_build_ai_outreach_codex_exec_command_uses_schema_and_output_file(tmp_path: Path):
    schema_path = tmp_path / "schema.json"
    output_path = tmp_path / "output.json"

    command = build_ai_outreach_codex_exec_command(
        codex_bin="/opt/homebrew/bin/codex",
        project_root=tmp_path,
        schema_path=schema_path,
        output_path=output_path,
        model="gpt-5.4",
    )

    assert command == [
        "/opt/homebrew/bin/codex",
        "exec",
        "--model",
        "gpt-5.4",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "-C",
        str(tmp_path),
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
        "-",
    ]


def test_generate_ai_outreach_draft_materializes_prompt_and_email(monkeypatch, tmp_path: Path):
    _write_sender_profile(tmp_path)
    jd_path = tmp_path / "jd.md"
    resume_path = tmp_path / "resume.md"
    jd_path.write_text("Cloudflare is hiring a Software Engineer, Realtime.", encoding="utf-8")
    resume_path.write_text(
        "Built distributed systems in Python and Go with monitoring and high-throughput data flows.",
        encoding="utf-8",
    )

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "subject": "Software Engineer, Realtime",
                    "body_markdown": "I'm reaching out about the Software Engineer, Realtime role at Cloudflare because I was interested in the role's focus on distributed systems, realtime data flows, and production reliability. That lines up well with the kind of backend and platform work I have done and want to keep building toward.\n\nGiven your role as Senior Engineer, I thought you might have useful perspective on the day-to-day work this role touches. In one recent role, I built high-throughput backend services and monitoring-heavy production workflows, and I've attached my resume for context.",
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":true}', stderr="codex stderr")

    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.shutil.which", lambda name: f"/opt/homebrew/bin/{name}")
    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.subprocess.run", fake_run)

    result = generate_ai_outreach_draft(
        AiOutreachPocRequest(
            jd_path=str(jd_path),
            resume_path=str(resume_path),
            company_name="Cloudflare",
            role_title="Software Engineer, Realtime",
            contact_name="Eduardo",
        ),
        project_root=tmp_path,
    )

    assert result.subject == "[AI POC] Software Engineer, Realtime"
    assert result.send_to_email == "asonti1@asu.edu"
    assert Path(result.prompt_path).exists()
    assert Path(result.schema_path).exists()
    assert Path(result.draft_json_path).exists()
    assert Path(result.email_markdown_path).exists()
    email_text = Path(result.email_markdown_path).read_text(encoding="utf-8")
    assert email_text.startswith("Hi Eduardo,")
    assert "I built Job Hunt Copilot" in email_text
    assert "Best," in email_text
    assert "Achyutaram Sonti" in email_text
    assert "asonti1@asu.edu" in email_text
    assert result.body_html is not None
    assert len(result.attachment_paths) == 2
    assert str(jd_path) in result.attachment_paths
    assert str(resume_path) in result.attachment_paths


def test_generate_github_project_selection_validates_payload_and_membership(monkeypatch, tmp_path: Path):
    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "selected_repo_name": "freeRTOS-visualizer",
                    "selected_repo_url": "https://github.com/hariharanragothaman/freeRTOS-visualizer",
                    "why_selected": "It has the clearest systems/tooling story and strong overlap with production-minded engineering.",
                    "observations": [
                        "it handles serial task-state parsing and keeps task-state history",
                        "it includes automatic reconnect with exponential backoff",
                        "it is packaged and tested like a usable tool rather than a one-off script",
                    ],
                    "runner_up_repo_names": ["dockpulse"],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.shutil.which", lambda name: f"/opt/homebrew/bin/{name}")
    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.subprocess.run", fake_run)

    result = generate_github_project_selection(
        GithubProjectSelectionRequest(
            contact_name="Hariharan Ragothaman",
            contact_company="AMD",
            contact_role="MTS Software Engineer",
            github_profile_url="https://github.com/hariharanragothaman",
            github_profile_bio="Member of Technical Staff @AMD",
            sender_background_summary="I am building Job Hunt Copilot and trying to push useful workflows toward more production-minded systems.",
            candidate_repos=[
                GithubRepoCandidate(
                    name="freeRTOS-visualizer",
                    url="https://github.com/hariharanragothaman/freeRTOS-visualizer",
                    description="Python Tool to visualize RTOS tasks in real-time",
                    language="Python",
                    topics=("freertos", "real-time"),
                    stars=25,
                    updated_at="2026-03-28T10:39:24Z",
                    readme_excerpt="Real-time visualization of FreeRTOS task states over serial with reconnect handling and CSV export.",
                ),
                GithubRepoCandidate(
                    name="dockpulse",
                    url="https://github.com/hariharanragothaman/dockpulse",
                    description="Container Resource Profiler & Right-Sizer for Docker",
                ),
            ],
        ),
        project_root=tmp_path,
    )

    assert result.selected_repo_name == "freeRTOS-visualizer"
    assert result.selected_repo_url == "https://github.com/hariharanragothaman/freeRTOS-visualizer"
    assert len(result.observations) == 3
    assert Path(result.prompt_path).exists()
    assert Path(result.schema_path).exists()
    assert Path(result.selection_json_path).exists()


def test_github_profile_resolver_scores_and_resolves_best_candidate(monkeypatch, tmp_path: Path):
    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        joined = " ".join(command)
        if "/search/users?q=Hariharan+Ragothaman+AMD&per_page=10" in joined:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "items": [
                            {"login": "hariharanragothaman"},
                            {"login": "hari-rag"},
                        ]
                    }
                ),
                stderr="",
            )
        if "/search/users?q=Hariharan+Ragothaman&per_page=10" in joined:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"items": [{"login": "hariharanragothaman"}]}),
                stderr="",
            )
        if "/search/users?q=hariharanragothaman&per_page=10" in joined:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"items": [{"login": "hariharanragothaman"}]}),
                stderr="",
            )
        if joined.endswith("/users/hariharanragothaman"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "login": "hariharanragothaman",
                        "html_url": "https://github.com/hariharanragothaman",
                        "name": "Hariharan Ragothaman",
                        "company": "@AMD",
                        "bio": "Member of Technical Staff @AMD",
                        "blog": "https://hariharanragothaman.github.io/",
                        "location": "Austin, TX",
                    }
                ),
                stderr="",
            )
        if joined.endswith("/users/hari-rag"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "login": "hari-rag",
                        "html_url": "https://github.com/hari-rag",
                        "name": "Hari Rag",
                        "company": None,
                        "bio": "Embedded tinkerer",
                        "blog": None,
                        "location": "Unknown",
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.shutil.which", lambda name: f"/opt/homebrew/bin/{name}")
    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.subprocess.run", fake_run)

    resolver = GithubProfileResolver()
    result = resolver.resolve_profile(
        GithubProfileResolutionRequest(
            contact_name="Hariharan Ragothaman",
            contact_company="AMD",
            contact_role="MTS Software Engineer",
            email="hariharan.ragothaman@amd.com",
        ),
        project_root=tmp_path,
    )

    assert result.resolved_login == "hariharanragothaman"
    assert result.resolved_github_url == "https://github.com/hariharanragothaman"
    assert result.confidence == "high"
    assert result.score is not None and result.score >= 90
    assert any("company field matches" in reason for reason in result.why_matched)
    assert len(result.candidates) == 2
    assert result.candidates[0].login == "hariharanragothaman"
    assert Path(result.request_path).exists()
    assert Path(result.resolution_json_path).exists()


def test_github_profile_researcher_fetches_all_public_repos(monkeypatch):
    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        joined = " ".join(command)
        if "/users/hariharanragothaman/repos?per_page=100&page=1&sort=updated" in joined:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [
                        {
                            "name": "freeRTOS-visualizer",
                            "html_url": "https://github.com/hariharanragothaman/freeRTOS-visualizer",
                            "description": "Python Tool to visualize RTOS tasks in real-time",
                            "language": "Python",
                            "topics": ["freertos", "real-time"],
                            "stargazers_count": 25,
                            "updated_at": "2026-03-28T10:39:24Z",
                        },
                        {
                            "name": "dockpulse",
                            "html_url": "https://github.com/hariharanragothaman/dockpulse",
                            "description": "Container Resource Profiler & Right-Sizer for Docker",
                            "language": "Python",
                            "topics": ["docker", "profiling"],
                            "stargazers_count": 10,
                            "updated_at": "2026-03-20T10:00:00Z",
                        },
                    ]
                ),
                stderr="",
            )
        if "/users/hariharanragothaman/repos?per_page=100&page=2&sort=updated" in joined:
            return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")
        if joined.endswith("/users/hariharanragothaman"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "html_url": "https://github.com/hariharanragothaman",
                        "login": "hariharanragothaman",
                        "name": "Hariharan Ragothaman",
                        "company": "@amd",
                        "bio": "Member of Technical Staff @AMD",
                        "blog": "https://hariharanragothaman.github.io/",
                        "location": "Austin, TX",
                    }
                ),
                stderr="",
            )
        if "/repos/hariharanragothaman/freeRTOS-visualizer/readme" in joined and "--jq .download_url" in joined:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="https://raw.githubusercontent.com/hariharanragothaman/freeRTOS-visualizer/main/README.md\n",
                stderr="",
            )
        if "/repos/hariharanragothaman/dockpulse/readme" in joined and "--jq .download_url" in joined:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="https://raw.githubusercontent.com/hariharanragothaman/dockpulse/main/README.md\n",
                stderr="",
            )
        if command[:2] == ["curl", "-L"] and "freeRTOS-visualizer" in command[2]:
            return subprocess.CompletedProcess(command, 0, stdout="Realtime visualization over serial with reconnect handling.", stderr="")
        if command[:2] == ["curl", "-L"] and "dockpulse" in command[2]:
            return subprocess.CompletedProcess(command, 0, stdout="Profiler and right-sizer for Docker workloads.", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.shutil.which", lambda name: f"/opt/homebrew/bin/{name}")
    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.subprocess.run", fake_run)

    researcher = GithubProfileResearcher()
    research = researcher.fetch_profile_research(profile_url="https://github.com/hariharanragothaman")

    assert research.login == "hariharanragothaman"
    assert research.display_name == "Hariharan Ragothaman"
    assert len(research.repo_candidates) == 2
    assert research.repo_candidates[0].name == "freeRTOS-visualizer"
    assert "reconnect" in (research.repo_candidates[0].readme_excerpt or "")


def test_github_profile_researcher_can_skip_readmes_and_enrich_selected_repo(monkeypatch):
    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        joined = " ".join(command)
        if "/users/hariharanragothaman/repos?per_page=100&page=1&sort=updated" in joined:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [
                        {
                            "name": "freeRTOS-visualizer",
                            "html_url": "https://github.com/hariharanragothaman/freeRTOS-visualizer",
                            "description": "Python Tool to visualize RTOS tasks in real-time",
                            "language": "Python",
                            "topics": ["freertos", "real-time"],
                            "stargazers_count": 25,
                            "updated_at": "2026-03-28T10:39:24Z",
                        }
                    ]
                ),
                stderr="",
            )
        if "/users/hariharanragothaman/repos?per_page=100&page=2&sort=updated" in joined:
            return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")
        if joined.endswith("/users/hariharanragothaman"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "html_url": "https://github.com/hariharanragothaman",
                        "login": "hariharanragothaman",
                        "name": "Hariharan Ragothaman",
                        "company": "@amd",
                        "bio": "Member of Technical Staff @AMD",
                        "blog": "https://hariharanragothaman.github.io/",
                        "location": "Austin, TX",
                    }
                ),
                stderr="",
            )
        if "/repos/hariharanragothaman/freeRTOS-visualizer/readme" in joined and "--jq .download_url" in joined:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="https://raw.githubusercontent.com/hariharanragothaman/freeRTOS-visualizer/main/README.md\n",
                stderr="",
            )
        if command[:2] == ["curl", "-L"] and "freeRTOS-visualizer" in command[2]:
            return subprocess.CompletedProcess(command, 0, stdout="Realtime visualization over serial with reconnect handling.", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.shutil.which", lambda name: f"/opt/homebrew/bin/{name}")
    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.subprocess.run", fake_run)

    researcher = GithubProfileResearcher()
    research = researcher.fetch_profile_research(
        profile_url="https://github.com/hariharanragothaman",
        include_readme_excerpts=False,
    )

    assert research.repo_candidates[0].readme_excerpt is None

    enriched = researcher.enrich_repo_candidate_with_readme(
        login=research.login,
        repo_candidate=research.repo_candidates[0],
    )

    assert "reconnect" in (enriched.readme_excerpt or "")


def test_generate_github_project_analysis_materializes_structured_analysis(monkeypatch, tmp_path: Path):
    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "project_summary": "A Python tool for visualizing FreeRTOS task states in real time over serial connections.",
                    "engineering_problem": "It turns low-level RTOS task-state output into a usable monitoring and debugging tool.",
                    "standout_observations": [
                        "it handles serial task-state parsing and keeps history rather than just showing a single live view",
                        "it includes reconnect behavior and CSV export, which makes it feel operational rather than purely visual",
                        "the repo shows packaging and testing discipline, which makes it easier to treat as a reusable tool",
                    ],
                    "why_it_is_a_good_hook": "The repo has a clear systems/tooling story and enough concrete implementation detail to support a specific outreach note.",
                    "connection_to_my_work": "I am building Job Hunt Copilot and trying to push a workflow into something more reliable and production-minded, so the overlap is in turning a useful concept into a practical tool.",
                    "conversation_angle": "I would ask how he decides which reliability and usability details are worth building into a tooling project like this.",
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout='{\"ok\":true}', stderr='')

    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.shutil.which", lambda name: f"/opt/homebrew/bin/{name}")
    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.subprocess.run", fake_run)

    result = generate_github_project_analysis(
        GithubProjectAnalysisRequest(
            contact_name="Hariharan Ragothaman",
            contact_company="AMD",
            contact_role="MTS Software Engineer",
            github_profile_bio="Member of Technical Staff @AMD",
            sender_background_summary="I am building Job Hunt Copilot and trying to make it more production-minded around orchestration, reliability, and usability.",
            selected_repo=GithubRepoCandidate(
                name="freeRTOS-visualizer",
                url="https://github.com/hariharanragothaman/freeRTOS-visualizer",
                description="Python Tool to visualize RTOS tasks in real-time",
                language="Python",
                topics=("freertos", "real-time"),
                stars=25,
                updated_at="2026-03-28T10:39:24Z",
                readme_excerpt="Real-time visualization of FreeRTOS task states over serial. Automatic reconnect with exponential backoff. CSV export on exit.",
            ),
        ),
        project_root=tmp_path,
    )

    assert "FreeRTOS task states" in result.project_summary
    assert len(result.standout_observations) == 3
    assert Path(result.prompt_path).exists()
    assert Path(result.schema_path).exists()
    assert Path(result.analysis_json_path).exists()


def test_generate_github_coffee_chat_draft_wraps_validated_email(monkeypatch, tmp_path: Path):
    _write_sender_profile(tmp_path)

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "subject": "Question about freeRTOS-visualizer",
                    "body_markdown": "\n\n".join(
                        [
                            "I spent some time going through your freeRTOS-visualizer repo, and it stood out because it feels like a real engineering tool rather than a quick demo. The serial task-state parsing, reconnect handling, and CSV export made it clear you were thinking about actual debugging workflow and usability.",
                            "I am building Job Hunt Copilot right now, and I am trying to push it in the same direction from useful prototype to something more robust and production-minded. I built it for my own job search to identify relevant roles and the right people to reach out to, parts of the workflow run autonomously, and I personally review every email before it goes out. This email is a live example of that workflow.",
                            "If you would be open to it, I would really appreciate a short 15-minute coffee chat to hear how you think about building projects like this and what makes them genuinely useful in practice. Would you be available sometime in the next two weeks? I am usually free on weekdays between 10 AM and 5 PM MT, and I can be flexible on weekends if that is easier.",
                        ]
                    ),
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.shutil.which", lambda name: f"/opt/homebrew/bin/{name}")
    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.subprocess.run", fake_run)

    result = generate_github_coffee_chat_draft(
        GithubCoffeeChatDraftRequest(
            contact_name="Hariharan",
            contact_company="AMD",
            contact_role="MTS Software Engineer",
            github_profile_url="https://github.com/hariharanragothaman",
            github_profile_bio="Member of Technical Staff @AMD",
            selected_repo=GithubRepoCandidate(
                name="freeRTOS-visualizer",
                url="https://github.com/hariharanragothaman/freeRTOS-visualizer",
                description="Python Tool to visualize RTOS tasks in real-time",
                language="Python",
                topics=("freertos", "real-time"),
                stars=25,
                updated_at="2026-03-28T10:39:24Z",
                readme_excerpt="Real-time visualization of FreeRTOS task states over serial. Automatic reconnect with exponential backoff. CSV export on exit.",
            ),
            project_summary="A Python tool for visualizing FreeRTOS task states in real time over serial connections.",
            engineering_problem="It turns low-level RTOS task-state output into a usable monitoring and debugging tool.",
            standout_observations=(
                "it handles serial task-state parsing and keeps history rather than just showing a single live view",
                "it includes reconnect behavior and CSV export, which makes it feel operational rather than purely visual",
                "the repo shows packaging and testing discipline, which makes it easier to treat as a reusable tool",
            ),
            connection_to_my_work="I am building Job Hunt Copilot and trying to push a workflow into something more reliable and production-minded, so the overlap is in turning a useful concept into a practical tool.",
            conversation_angle="I would ask how he decides which reliability and usability details are worth building into a tooling project like this.",
            availability_window="10 AM and 5 PM MT",
        ),
        project_root=tmp_path,
    )

    assert result.subject == "Question about freeRTOS-visualizer"
    assert Path(result.prompt_path).exists()
    assert Path(result.schema_path).exists()
    assert Path(result.draft_json_path).exists()
    assert Path(result.email_markdown_path).exists()
    email_text = Path(result.email_markdown_path).read_text(encoding="utf-8")
    assert email_text.startswith("Hi Hariharan,")
    assert "This email is a live example of that workflow." in email_text
    assert "15-minute coffee chat" in email_text
    assert "Best," in email_text
    assert "Achyutaram Sonti" in email_text
    assert result.body_html is not None


def test_run_github_personalized_outreach_poc_orchestrates_all_stages(monkeypatch, tmp_path: Path):
    selected_repo = GithubRepoCandidate(
        name="freeRTOS-visualizer",
        url="https://github.com/hariharanragothaman/freeRTOS-visualizer",
        description="Python Tool to visualize RTOS tasks in real-time",
        language="Python",
        topics=("freertos", "real-time"),
        stars=25,
        updated_at="2026-03-28T10:39:24Z",
        readme_excerpt="Real-time visualization of FreeRTOS task states over serial. Automatic reconnect with exponential backoff. CSV export on exit.",
    )

    class FakeResolver:
        def resolve_profile(self, request, *, project_root):  # type: ignore[no-untyped-def]
            assert request.contact_name == "Hariharan Ragothaman"
            return GithubProfileResolutionResult(
                run_id="resolver-run",
                run_dir=str(tmp_path / "ops" / "github-personalization-poc" / "resolver-run"),
                contact_name=request.contact_name,
                contact_company=request.contact_company,
                request_path=str(tmp_path / "resolver-request.json"),
                resolution_json_path=str(tmp_path / "resolver-resolution.json"),
                resolved_github_url="https://github.com/hariharanragothaman",
                resolved_login="hariharanragothaman",
                confidence="high",
                score=100,
                why_matched=("GitHub display name exactly matches the contact name.",),
                candidates=(),
            )

    class FakeResearcher:
        def fetch_profile_research(self, *, profile_url, include_readme_excerpts=True):  # type: ignore[no-untyped-def]
            assert profile_url == "https://github.com/hariharanragothaman"
            assert include_readme_excerpts is False
            return GithubProfileResearch(
                profile_url=profile_url,
                login="hariharanragothaman",
                display_name="Hariharan Ragothaman",
                company="@AMD",
                bio="Member of Technical Staff @AMD",
                blog="https://hariharanragothaman.github.io/",
                location="Austin, TX",
                repo_candidates=(selected_repo,),
            )

        def enrich_repo_candidate_with_readme(self, *, login, repo_candidate):  # type: ignore[no-untyped-def]
            assert login == "hariharanragothaman"
            return repo_candidate

    def fake_generate_selection(request, *, project_root, codex_bin=None):  # type: ignore[no-untyped-def]
        assert request.github_profile_url == "https://github.com/hariharanragothaman"
        return GithubProjectSelectionResult(
            run_id="selector-run",
            run_dir=str(tmp_path / "ops" / "github-personalization-poc" / "selector-run"),
            contact_name=request.contact_name,
            contact_company=request.contact_company,
            prompt_path=str(tmp_path / "selector-prompt.md"),
            schema_path=str(tmp_path / "selector-schema.json"),
            request_path=str(tmp_path / "selector-request.json"),
            selection_json_path=str(tmp_path / "selector-selection.json"),
            codex_stdout_path=str(tmp_path / "selector-stdout.txt"),
            codex_stderr_path=str(tmp_path / "selector-stderr.txt"),
            selected_repo_name=selected_repo.name,
            selected_repo_url=selected_repo.url,
            why_selected="Strong systems/tooling hook.",
            observations=("observation one", "observation two"),
            runner_up_repo_names=(),
        )

    def fake_generate_analysis(request, *, project_root, codex_bin=None):  # type: ignore[no-untyped-def]
        assert request.selected_repo.name == "freeRTOS-visualizer"
        return GithubProjectAnalysisResult(
            run_id="analysis-run",
            run_dir=str(tmp_path / "ops" / "github-personalization-poc" / "analysis-run"),
            contact_name=request.contact_name,
            contact_company=request.contact_company,
            prompt_path=str(tmp_path / "analysis-prompt.md"),
            schema_path=str(tmp_path / "analysis-schema.json"),
            request_path=str(tmp_path / "analysis-request.json"),
            analysis_json_path=str(tmp_path / "analysis.json"),
            codex_stdout_path=str(tmp_path / "analysis-stdout.txt"),
            codex_stderr_path=str(tmp_path / "analysis-stderr.txt"),
            project_summary="A Python tool for visualizing FreeRTOS task states in real time over serial connections.",
            engineering_problem="It turns low-level RTOS task-state output into a usable monitoring and debugging tool.",
            standout_observations=("observation one", "observation two"),
            why_it_is_a_good_hook="Clear systems/tooling story.",
            connection_to_my_work="Overlap with turning a useful concept into a practical tool.",
            conversation_angle="How he decides which reliability details are worth building in.",
        )

    def fake_generate_draft(request, *, project_root, codex_bin=None):  # type: ignore[no-untyped-def]
        assert request.selected_repo.name == "freeRTOS-visualizer"
        assert request.project_summary.startswith("A Python tool")
        return GithubCoffeeChatDraftResult(
            run_id="draft-run",
            run_dir=str(tmp_path / "ops" / "github-personalization-poc" / "draft-run"),
            contact_name=request.contact_name,
            contact_company=request.contact_company,
            subject="Question about freeRTOS-visualizer",
            body_text="Hi Hariharan,\n\nBody.\n\nBest,\nAchyutaram Sonti\n",
            body_html="<html><body><p>Body.</p></body></html>\n",
            prompt_path=str(tmp_path / "draft-prompt.md"),
            schema_path=str(tmp_path / "draft-schema.json"),
            request_path=str(tmp_path / "draft-request.json"),
            draft_json_path=str(tmp_path / "draft.json"),
            email_markdown_path=str(tmp_path / "email.md"),
            codex_stdout_path=str(tmp_path / "draft-stdout.txt"),
            codex_stderr_path=str(tmp_path / "draft-stderr.txt"),
        )

    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.generate_github_project_selection", fake_generate_selection)
    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.generate_github_project_analysis", fake_generate_analysis)
    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.generate_github_coffee_chat_draft", fake_generate_draft)

    result = run_github_personalized_outreach_poc(
        GithubPersonalizedOutreachPocRequest(
            contact_name="Hariharan Ragothaman",
            contact_company="AMD",
            contact_role="MTS Software Engineer",
            sender_background_summary="I am building Job Hunt Copilot and trying to push useful workflows toward production-minded systems.",
            availability_window="10 AM and 5 PM MT",
            email="hariharan.ragothaman@amd.com",
        ),
        project_root=tmp_path,
        resolver=FakeResolver(),
        researcher=FakeResearcher(),
    )

    assert result.resolution.resolved_login == "hariharanragothaman"
    assert result.research.login == "hariharanragothaman"
    assert result.selection.selected_repo_name == "freeRTOS-visualizer"
    assert result.analysis.engineering_problem.startswith("It turns low-level")
    assert result.draft.subject == "Question about freeRTOS-visualizer"


def test_send_ai_outreach_draft_uses_requested_recipient_and_attachments(tmp_path: Path):
    run_dir = tmp_path / "ops" / "ai-outreach-poc" / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    resume_path = tmp_path / "resume.pdf"
    jd_path = tmp_path / "jd.md"
    resume_path.write_bytes(b"%PDF-1.4\n")
    jd_path.write_text("jd", encoding="utf-8")
    draft = generate_fake_draft(run_dir=run_dir, resume_path=resume_path, jd_path=jd_path)

    class RecordingSender:
        def __init__(self) -> None:
            self.messages = []

        def send(self, message):  # type: ignore[no-untyped-def]
            self.messages.append(message)
            from job_hunt_copilot.outreach import SendAttemptOutcome

            return SendAttemptOutcome(
                outcome="sent",
                thread_id="thread-1",
                delivery_tracking_id="delivery-1",
                sent_at="2026-05-28T20:00:00Z",
            )

    sender = RecordingSender()
    result = send_ai_outreach_draft(
        draft,
        project_root=tmp_path,
        sender=sender,
    )

    assert result.outcome == "sent"
    assert sender.messages[0].recipient_email == "me@example.com"
    assert tuple(sender.messages[0].attachment_paths) == (str(resume_path), str(jd_path))
    assert Path(result.send_result_path).exists()


def generate_fake_draft(*, run_dir: Path, resume_path: Path, jd_path: Path):  # type: ignore[no-untyped-def]
    from job_hunt_copilot.ai_outreach_poc import AiOutreachDraftResult

    return AiOutreachDraftResult(
        run_id="run-1",
        run_dir=str(run_dir),
        company_name="Acme",
        role_title="Platform Engineer",
        contact_name="Taylor",
        send_to_email="me@example.com",
        subject="[AI POC] Platform Engineer",
        body_text="Hi Taylor,\n\nBody.\n\nBest,\nAchyutaram\n",
        body_html="<html><body><p>Body</p></body></html>\n",
        prompt_path=str(run_dir / "prompt.md"),
        schema_path=str(run_dir / "schema.json"),
        request_path=str(run_dir / "request.json"),
        draft_json_path=str(run_dir / "draft.json"),
        email_markdown_path=str(run_dir / "email.md"),
        codex_stdout_path=str(run_dir / "codex.stdout.txt"),
        codex_stderr_path=str(run_dir / "codex.stderr.txt"),
        jd_text_path=str(run_dir / "jd.txt"),
        resume_text_path=str(run_dir / "resume.txt"),
        attachment_paths=(str(resume_path), str(jd_path)),
    )
