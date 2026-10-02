# GitHub Actions connection

Public downloader: https://github.com/Byadil/anime-zak-downloader (ID 1401385055).
Private transcoder: https://github.com/Byadil/anime-zak-transcoder (ID 1401395499).
Both use main. Workflows are download.yml and transcode.yml.

The Cloudflare Worker discovered in this session is:
https://animezak-app.85amiaksahib.workers.dev

## Current deployment blockers

The existing Worker has ASSETS, DB and DOWNLOADER bindings. It has no MEDIA_BUCKET
binding and no configured application signing or media-job secrets. The available
Cloudflare OAuth connection cannot list R2 buckets (HTTP 403). Do not enable the
Actions backends until private R2 storage and scoped dispatch tokens are configured.

## Deploy the application integration

Use the existing application deployment process after configuring real storage,
app and media origins. Apply db/pipeline-migrations/20261001_github_media.sql once
for an existing database, then 20261002_github_downloads.sql. Fresh databases need
db/schema.sql and the existing pipeline migrations in sequence.

Configure MEDIA_BUCKET as a private R2 bucket. Keep direct bucket public access off.
Use separate canonical HTTPS app/media origins. MEDIA_WORKER_ORIGIN must match the
app Worker origin and both repositories' MEDIA_WORKER_ORIGIN Actions variable.

Set the application's GITHUB_MEDIA_TOKEN and GITHUB_DOWNLOAD_TOKEN as Worker
secrets. Use fine-grained GitHub tokens with Actions read/write access limited to
the corresponding repository, and expiry dates. Do not reuse a local Git credential
or paste tokens into repository files. Configure JWT_SECRET and MEDIA_JOB_SECRET
using the normal application secret provisioning process.

wrangler.toml includes the verified repository IDs and branch/workflow settings.
Switch DOWNLOAD_BACKEND and MEDIA_TRANSCODE_BACKEND from runtime to github only
after staging smoke tests. The template remains on runtime until storage exists.

## Download behavior

Existing /api/dl/start, /status/:jobId, /file/:jobId, /job/:jobId, /jobs and /health
routes are connected in the Cloudflare app Worker. The public workflow receives
only an internal job ID. Its OIDC-authenticated controller claims the URL from the
Worker and returns the finished video to R2. No media artifacts are published on
GitHub. The browser receives a separate random access ID that is never dispatched
to GitHub. Keep that access ID private, as it authorizes file retrieval/cancellation.

Output is limited to 90 MiB to fit a standard Cloudflare request upload limit.
Jobs expire after two hours; cron removes expired objects. Global capacity is two
active jobs and twenty dispatches per hour. Retries start new jobs. Source and
extractor site restrictions still apply; no DRM or authentication bypass is added.

The existing Express/local Python downloader remains available for local previews.
The GitHub downloader integration runs on the Cloudflare Worker deployment.

## Transcoding behavior

The private workflow builds Dockerfile.media-encoder automatically using the pinned
Python base recorded in transcode.yml. The host controller accepts either a local
immutable sha256 image ID from that build or an explicitly configured registry
digest. No registry account or MEDIA_ENCODER_IMAGE variable is required for the
default workflow. Update the pinned base after reviewing image updates.

## Verification

npm run test:github-download
npm run test:github-media
python tests/github_runner_test.py

Repository CI validates Python code and controller security behavior. The private
repository CI runs real FFmpeg media fixtures. Live job smoke tests require R2 and
the application configuration above. A passing CI workflow alone does not prove
that the deployed website can process a job.
