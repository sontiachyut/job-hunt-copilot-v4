## GitHub-Personalized Outreach POC

### Goal

Build a separate outreach flow that uses a contact's public GitHub presence to draft a short coffee-chat email.

This is not a job-ask email. The goal is:

1. establish real common ground from a concrete GitHub project or repo theme
2. show credibility through `Job Hunt Copilot`
3. ask for a short 15-minute conversation

### Architecture Direction

Use a hybrid pipeline:

- deterministic Python for control flow and evidence collection
- bounded AI steps for project selection, project analysis, and email drafting
- human review before send

Do not start with a free-form agent.

### Proposed Pipeline

1. `github_resolver`
   - resolve a GitHub profile from contact name/company/title
   - store confidence and candidate URL

2. `github_research_extractor`
   - fetch profile metadata
   - fetch pinned or recent repos
   - fetch README and key repo metadata
   - build compact structured research records

3. `project_selector` (AI step)
   - choose the best repo/project to mention in the email

4. `project_analyzer` (AI step)
   - explain what engineering problem the project is solving
   - identify specific technical details worth mentioning
   - connect the project to the sender's own work

5. `coffee_chat_drafter` (AI step)
   - draft a 3-paragraph email
   - use the selected repo and analysis
   - include a short `Job Hunt Copilot` credibility block
   - ask for a 15-minute conversation

### Email Structure

#### Paragraph 1: Common Ground

- mention one specific GitHub repo or project
- mention 1-2 concrete technical observations
- avoid generic praise

#### Paragraph 2: Connection + Credibility

- connect the project to something the sender is building
- mention `Job Hunt Copilot`
- say it helps identify relevant roles and the right people to reach out to
- say parts of the workflow run autonomously
- say every email is personally reviewed before sending
- mention that the email is a live example of that workflow

#### Paragraph 3: Call to Action

- ask for a short 15-minute coffee chat
- say the conversation would be about how they think about building systems/projects like this and what makes them genuinely useful in practice
- ask about availability in the next two weeks
- include the sender's availability window

### Drafter Prompt

```text
You are drafting a cold coffee-chat email to an engineer.

Your goal is to write a short, natural email that:
- starts from a real GitHub-based common ground
- shows I spent time understanding one of their projects
- connects that project to something I am building
- briefly establishes my credibility through Job Hunt Copilot
- asks for a 15-minute conversation in the next two weeks

You will receive:
- recipient first name
- recipient company
- recipient role/title
- selected GitHub repo or project
- 1-3 specific observations about that repo/project
- a short explanation of how that project connects to my work
- a short summary of Job Hunt Copilot
- my availability window

Write the email using exactly 3 paragraphs:

Paragraph 1:
- Mention the selected GitHub repo or project by name.
- Mention 1-2 concrete technical observations.
- The observations should sound like I actually read the repo/project.
- Do not use generic praise like “impressive profile” or “great work.”
- Do not say I have been following their work unless the input explicitly says that.

Paragraph 2:
- Connect their project to something I am building.
- Mention Job Hunt Copilot naturally.
- Briefly explain that I built Job Hunt Copilot for my own job search to identify relevant roles and the right people to reach out to.
- Mention that parts of the workflow run autonomously.
- Mention that I personally review every email before it goes out.
- Make clear that this email is a live example of that workflow.
- This paragraph should establish credibility, not sound like a product pitch.

Paragraph 3:
- Ask for a short 15-minute coffee chat.
- Say that I would like to hear how they think about building projects/systems like this and what makes them genuinely useful in practice.
- Ask whether they are available sometime in the next two weeks.
- Mention that I am usually free on weekdays between the provided availability window and can be flexible on weekends if needed.
- Do not ask for a job.
- Do not ask for a referral.

Style requirements:
- Natural, concise, technical, and human
- Not formal
- Not overly enthusiastic
- Not templated or robotic
- No flattery
- No exaggerated claims
- No bullet points
- No subject line unless explicitly requested
- Keep the email body under 220 words

Important:
- The GitHub/project hook is the main reason for the email.
- Job Hunt Copilot is supporting credibility, not the main topic.
- The call to action should feel easy to say yes to.

Return only the final email body.
```

### Current Example Contact

The strongest verified example so far is:

- `Hariharan Ragothaman` at `AMD`
- GitHub: `https://github.com/hariharanragothaman`
- useful repo hook: `freeRTOS-visualizer`

Why this repo is a good hook:

- concrete systems tool, not a toy repo
- clear reliability/operability details
- visible packaging, testing, and CI
- natural connection to production-minded engineering
