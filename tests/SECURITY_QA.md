# VSub Studio: application and security checks

Windows working tree based on `eb6af23`, tested on 2026-11-21. This includes local
uncommitted changes. The media editing workflow passed, but the findings below
remain open. This is not a security sign-off for a shared or public deployment.

## Findings from code review

| Priority | Finding and impact | Recommended change |
| --- | --- | --- |
| High | Project deletion only checks that its computed target is a directory before removing the whole tree. It does not establish that the target is one project directly inside the job root. An invalid ID from a member could cause loss of unrelated studio data. (`backend/api/projects.py:153-157`, `backend/store/projects.py:314-333`) | Enforce the boundary in the store for every caller: accept only valid IDs, resolve the target, require a direct child of the jobs directory and verify project identity before deleting anything. |
| High | The OpenAI client combines a caller-selected endpoint with the host's `OPENAI_API_KEY` fallback. On a configured host, that can disclose its credential to an unintended provider. (`backend/api/ai.py:39-44`, `backend/core/translate.py:976-986`) | Use host credentials only with a destination configured by the host. Require separate explicit credentials for custom destinations; require HTTPS outside loopback. |
| High | The shared dashboard inserts saved language metadata into HTML. Unknown language codes are displayed verbatim, so data saved by one member can be interpreted as markup in another member's browser. (`frontend/js/films.js:4-7,41-43,172-179`) | Render values as text, validate language codes server-side, and apply the same rule to file names and job details in `source.js` and `progress.js`. |
| Medium | The upload byte limit is enforced when copying an already-parsed multipart file. On the installed FastAPI version, parsing occurs before route dependencies: even an ultimately rejected request can consume temporary disk space. (`backend/api/media.py:40-59`, `backend/main.py:89-91`) | Authenticate and enforce a streaming request-body limit before multipart parsing; configure the same limit at the ingress, including for requests without a declared length. |

These are static findings. No destructive request, credential forwarding to a real
provider, script injection or resource-exhaustion test was performed.

## Verification

| Check | Observed result |
| --- | --- |
| Python 3.12.13, full pytest suite | 898 passed, 76.80% backend line coverage. One Starlette TestClient deprecation warning. |
| New media regression tests (`test_private_media.py`) | Authenticated full and ranged playback return the expected bytes and `no-store`. The same stream returns 401 after logout. An upload just over the configured file limit returns 413 and leaves no partial upload in the destination directory. This last check does not test the multipart spool limit. |
| Chrome, real loopback server, fresh profile | Invited registration, film creation, synthetic three-second MP4 and two-cue SRT upload, editing and saving, SRT/VTT export and subtitle burn-in all passed. Checked downloaded text, MP4 dimensions and duration, and 401 on the old download after logout. Re-login at a 390px viewport restored the library. No uncaught JavaScript errors in this flow. |
| Static frontend | All 18 JavaScript files passed `node --check`. The frontend-serving and privacy subset also passed after a concurrent theme change. |
| Android, isolated offline Gradle build | Debug and release APKs built. `lintDebug`: 0 errors, 8 warnings, including WebView JavaScript and backup rules. `testDebugUnitTest`: no test sources. Release currently uses debug signing; do not use that artifact for production distribution. |
| Lockfile and environment | `uv lock --check --offline` passed. `uv pip check` found incomplete `orjson` metadata and a `gradio`/`huggingface-hub` version conflict in the local virtual environment. |

`uv audit --locked --no-dev --python-version 3.12 --python-platform windows`
reported **140 advisories across 202 packages checked** including optional
features. Excluding all optional groups reported **26 advisories across 56
packages checked**. Some advisory IDs describe the same upstream issue. These
counts concern the lockfile, not demonstrated vulnerabilities in the application.
Prioritize packages in the actual deployment, update the lockfile in a separate
change, and retest the affected translation and media features.

All application data, test accounts and media used in these checks were temporary.
No live AI account, downloaded model, real user video, production database,
Redis service or physical Android device was used. The browser smoke test used
imported subtitles, not live ASR, translation or voice synthesis.
