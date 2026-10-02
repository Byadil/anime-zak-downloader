# anime-zak-downloader

Visibility: public

The website integration requires its private R2 binding, database migrations and
scoped GitHub dispatch token configuration before processing live jobs.
The workflow receives only a job UUID; source URLs and cloud keys are not passed
in workflow inputs. MEDIA_WORKER_ORIGIN is configured as an Actions variable.
No media is published as GitHub artifacts. See docs/GITHUB_ACTIONS_CONNECTION.md.
