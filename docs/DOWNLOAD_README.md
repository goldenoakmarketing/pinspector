# PinSpector — free local business research

Investigate public business listings, inspect captured sources, and follow
connections through domains, phone numbers, published license claims, and business
names. Runs locally on Windows with optional local AI. This is a source beta;
follow the footprint behind the business.

## What it does

- Search a category and city, or investigate known business websites.
- Capture source evidence and keep it separate from model interpretations.
- Discover identifier connections and possible name variants across listings.
- Review findings and export reports with source references.

Name similarity is a research lead, not proof of common ownership. Generic name
overlap and conflicting service categories are filtered. Maps discovery is
experimental, bounded, and sensitive to layout changes and access gates.

## Setup

1. Install Python 3.10 or newer, then extract the entire archive to a writable folder.
2. Run `Start PinSpector.cmd`. Dependencies install into this application's private environment. No administrator launch is needed.
3. Try the fictional demo first. For live Maps collection, Edge or Chrome must be available; `Install Browser.cmd` can install a separate Chromium if needed.
4. For reasoning, start your own local Ollama or compatible runtime. In Settings, detect installed models and select one. Qwen 2.5 7B is the tested model. No weights are bundled or automatically downloaded. Hardware requirements vary; allow adequate RAM and disk for the chosen model.
5. Phone lookups require each user to supply their own Veriphone API key under Settings > Phone lookup. No shared key or lookup credits are included. Third-party terms and quotas apply. Without a key, website, profile, and other evidence collection remain available.

For step-by-step instructions, ports, and connection troubleshooting, read [Connect your local model](docs/LOCAL_MODEL_SETUP.md).

The default dashboard is http://127.0.0.1:8768 . Keep it local; do not expose it through a public tunnel. Settings supports other local runtime ports. The helper detects common Ollama ports without altering other applications.

## Data and privacy

Investigations, source captures, and logs stay in `data` beside the app. Website and Maps collection send requests to those services; phone lookup sends the selected business phone to Veriphone. Local reasoning sends collected evidence to the configured local runtime. Attribution links only navigate when clicked; no background marketing telemetry is included.

Phone keys are protected with Windows DPAPI for the current Windows user. Copying data to another user or computer may require reconnecting the key. General settings and investigation exports exclude the key. Existing backup copies made before migration may still contain older plaintext keys; encrypted current storage does not change those backups.

Scans connect domains, phone numbers, published license numbers, partner statements, and similar names with source evidence. Similar names alone do not merge businesses. Conclusions are evidence-based assessments, not proof of fraud or location eligibility. Discovery is bounded and cannot promise every listing.

## License and contributions

Released under **GPL-3.0-only**. See [LICENSE](LICENSE) for the complete terms.
Dependencies keep their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
No browser binaries or model weights are distributed in this source package.

Development instructions are in [CONTRIBUTING](docs/CONTRIBUTING.md), and private
data guidance is in [SECURITY](docs/SECURITY.md).

## Release status

Clean-machine testing and a current dependency audit remain before a public launch.
There is no signed installer; users run the source with Python. The clean export
excludes personal scans, credentials, logs, model weights, machine-specific model
launchers, and the author's Git history. It includes synthetic demo pages.

Built by [Golden Oak](https://www.goldenoakmarketing.com/) · [Clymb Local](https://clymblocal.com/)
