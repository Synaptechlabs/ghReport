# GitHub Repository Report

A small command-line utility that produces a detailed report for a GitHub repository using the GitHub REST API.

The report combines repository metadata, activity statistics, language information and tracked-file storage analysis into a single terminal-friendly view.

## Features

The report includes:

- Repository description and visibility
- Default branch
- Primary language and licence
- Fork and archive status
- GitHub Pages status
- Repository creation date and age
- Last push date
- Activity classification
- Stars, watchers and forks
- Open issues and pull requests
- Commit count
- Branch and tag counts
- Contributor count
- Releases and latest release
- Language breakdown
- Tracked file count and size
- GitHub repository size
- GitHub Pages storage usage
- File-size breakdown by category
- 20 largest tracked files

Example:

```text
SYNAPTECH LABS — REPOSITORY REPORT
========================================================

REPOSITORY
--------------------------------------------------------
Repository:          synaptechlabs/example
Description:         Example repository
Visibility:          Public
Default branch:      main
Primary language:    Python
License:             MIT
Fork:                No
Archived:            No
GitHub Pages:        No

ACTIVITY
--------------------------------------------------------
Created:             2026-05-19
Repository age:      87 days
Last push:           2026-08-13
Days since push:     1
Activity status:     Active

GITHUB STATISTICS
--------------------------------------------------------
Stars:               4
Watchers:            1
Forks:               0
Open issues:         2
Open pull requests:  1
Commits:             37
Branches:            2
Tags:                3
Contributors:        2
Releases:            1

LANGUAGES
--------------------------------------------------------
Python                  18.42 KB     92.1%
Shell                     1.58 KB      7.9%

STORAGE
--------------------------------------------------------
Files:               24
Tracked file size:   20.00 KB
...
```

## Requirements

- Python 3
- A GitHub account
- A GitHub Personal Access Token
- Internet access to the GitHub API

The current version uses the macOS `security` command to retrieve the GitHub token from **macOS Keychain**, so the supplied authentication code is intended for macOS.

No third-party Python packages are required.

## Authentication

The program authenticates with GitHub using a Personal Access Token (PAT).

**Do not put your GitHub token directly in the Python source code.**

The supplied version stores the token in macOS Keychain and retrieves it when the program starts.

### 1. Create a GitHub Personal Access Token

Create a **fine-grained personal access token** in your GitHub account settings.

GitHub's token settings are available at:

https://github.com/settings/personal-access-tokens

Choose the repositories that you want the report tool to be able to inspect.

Because this is a reporting tool, use **read-only permissions** wherever possible.

At minimum, the token needs access to repository metadata and contents. Some statistics may require additional read permissions depending on the repository and your GitHub account configuration.

Avoid granting write permissions: this program does not need to modify repositories.

### 2. Store the token in macOS Keychain

The program expects a generic Keychain item with the service name:

```text
github-api-token
```

Create it with:

```bash
security add-generic-password \
    -a "$USER" \
    -s "github-api-token" \
    -w
```

macOS will prompt:

```text
password data for new item:
```

Paste your GitHub Personal Access Token.

The token is then stored by macOS Keychain rather than in the program.

### Updating the token

If the token expires or you create a replacement token:

```bash
security add-generic-password \
    -a "$USER" \
    -s "github-api-token" \
    -w \
    -U
```

Enter the new token when prompted.

### Deleting the token

To remove the stored token:

```bash
security delete-generic-password \
    -a "$USER" \
    -s "github-api-token"
```

### Checking that the token exists

You can verify that the Keychain entry exists with:

```bash
security find-generic-password \
    -a "$USER" \
    -s "github-api-token"
```

To retrieve the actual token:

```bash
security find-generic-password \
    -a "$USER" \
    -s "github-api-token" \
    -w
```

**Warning:** the second command prints the token to the terminal.

## Authentication on Linux and Windows

The current program uses macOS Keychain and therefore requires a small authentication change on Linux or Windows.

A simple cross-platform alternative is to use the `GITHUB_TOKEN` environment variable.

Replace the Keychain-based token retrieval with:

```python
def get_github_token():
    token = os.environ.get("GITHUB_TOKEN")

    if not token:
        print("Error: GITHUB_TOKEN environment variable is not set.")
        sys.exit(1)

    return token
```

Then set the environment variable before running the program.

### Linux / macOS

```bash
export GITHUB_TOKEN="your_token_here"
```

Then:

```bash
python3 ghReport.py OWNER/REPO
```

### Windows PowerShell

```powershell
$env:GITHUB_TOKEN="your_token_here"
python ghReport.py OWNER/REPO
```

Environment variables are convenient, but take appropriate care with shell history, scripts and configuration files containing credentials.

## Usage

Run the program with a GitHub repository in `OWNER/REPO` format:

```bash
python3 ghReport.py OWNER/REPO
```

For example:

```bash
python3 ghReport.py synaptechlabs/gss-agents
```

The repository does **not** need to be cloned locally.

All repository information is retrieved remotely through the GitHub API.

## Making It Executable on macOS/Linux

The script contains:

```text
#!/usr/bin/env python3
```

so it can be made directly executable:

```bash
chmod +x ghReport.py
```

Then:

```bash
./ghReport.py synaptechlabs/gss-agents
```

You can also place the script somewhere on your `$PATH` and invoke it like any other command-line utility.

## Activity Status

Repositories are given a simple activity classification based on the date of the most recent push:

| Time since last push | Status |
|---|---|
| Less than 30 days | Active |
| 30–89 days | Quiet |
| 90–364 days | Dormant |
| 365+ days | Stale |
| Archived repository | Archived |

These classifications are only intended as a quick personal project-management indicator.

A repository being classified as `Stale` does not necessarily mean there is anything wrong with it.

## Storage Reporting

The program requests the Git tree for the repository's default branch and recursively examines its blobs.

This means the storage section represents **tracked files in the current default-branch tree**.

It does not represent the complete size of the Git repository including all historical objects.

Files are grouped into categories such as:

- HTML
- PDF
- Images
- CSS / JavaScript
- Fonts
- Source
- Configuration
- Other

The report also lists the 20 largest tracked files.

## GitHub Pages Limit

The program currently uses:

```python
PAGES_LIMIT = 1_000_000_000
```

to represent a 1 GB GitHub Pages published-site limit.

The resulting percentage is intended as a convenient storage indicator for repositories being used to publish a GitHub Pages site.

For repositories that are not GitHub Pages sites, this value can simply be ignored.

## API Behaviour

The program uses several GitHub REST API endpoints rather than cloning the repository.

For large collections such as commits, branches and contributors, it uses GitHub's pagination information to obtain counts without unnecessarily downloading every object merely to count them.

The repository tree is requested recursively so that tracked files and their sizes can be analysed.

GitHub may truncate recursive tree responses for extremely large repositories. If this occurs, the program stops rather than presenting an incomplete storage report as though it were complete.

## Private Repositories

Private repositories can be reported if:

1. Your GitHub account has access to the repository.
2. Your Personal Access Token has permission to access it.

Do not give the token access to private repositories that you do not want this tool to inspect.

## Security

A few basic rules are strongly recommended:

- Never commit a Personal Access Token to Git.
- Never put a token directly in `ghReport.py`.
- Prefer fine-grained Personal Access Tokens.
- Grant only the repositories the tool actually needs.
- Use read-only permissions wherever possible.
- Give tokens an expiration date where practical.
- Revoke tokens that are no longer used.
- Treat a token like a password.

If a token is accidentally committed to a public repository, revoke it immediately and create a replacement.

## Why?

This started as a small local Python utility for keeping track of the storage used by a GitHub Pages repository.

Once the tool began using the GitHub API, it became useful to combine the storage information with the repository information GitHub already provides.

The result is a compact command-line overview of a repository without needing to browse several different GitHub pages.

## Licence

Add the licence of your choice before publishing the project.