# Profile hub

`generate.py` draws the card at the top of my profile README in the style of [CheckMyGit](https://checkmygit.com). The [Profile hub workflow](../.github/workflows/hub.yml) re-renders it daily and whenever this folder changes, then publishes `hub.svg` to the `output` branch that the README points at.

## Settings (`config.json`)

| Key | What it does |
| --- | --- |
| `username` | The GitHub account to draw. |
| `tagline` | The line under "Welcome to …'s Hub". |
| `tags` | Your own sidebar tags. Automatic ones (Mobile, Consistent, …) fill the rest, up to four. |
| `stats` | The four tiles, from `repos`, `stars`, `followers`, `years`, `contributions` and `languages`. |
| `techStack` | The chips under Core Technologies. Leave it empty to show your top languages instead. |
| `credit` | Shows "Inspired by CheckMyGit" in the banner when the title leaves room for it. |

Name, avatar, bio, company, location and website come from your GitHub profile, so editing those on GitHub updates the card on the next run.

## Rendering locally

```bash
pip install -r hub/requirements.txt
GITHUB_TOKEN=$(gh auth token) python hub/generate.py   # writes hub/dist/hub.svg
```
