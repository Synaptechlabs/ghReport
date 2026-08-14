#!/usr/bin/env python3

import sys
import os
import re
import json
import urllib.request
import urllib.parse
import subprocess

from pathlib import PurePosixPath
from collections import defaultdict
from datetime import datetime, timezone


# ----------------------------------------------------------------------
# Command-line arguments
#
# Usage:
#
#     ./ghReport.py OWNER/REPO
#
# Example:
#
#     ./ghReport.py synaptechlabs/gss-agents
# ----------------------------------------------------------------------

if len(sys.argv) != 2:
    print(f"Usage: {sys.argv[0]} OWNER/REPO")
    sys.exit(1)

REPO = sys.argv[1]


# GitHub Pages published-site limit: 1 GB
PAGES_LIMIT = 1_000_000_000


# Directories that we don't want included in the storage report.
IGNORE_DIRS = {
    ".git",
    ".github",
    "__pycache__",
}


# File extensions grouped into useful categories.
CATEGORIES = {
    "HTML": {".html", ".htm"},
    "PDF": {".pdf"},
    "Images": {
        ".png", ".jpg", ".jpeg", ".gif",
        ".webp", ".svg"
    },
    "CSS / JS": {
        ".css", ".js"
    },
    "Fonts": {
        ".woff", ".woff2", ".ttf", ".otf"
    },
    "Source": {
        ".c", ".h",
        ".cpp", ".cc", ".cxx", ".hpp",
        ".py",
        ".swift",
        ".go",
        ".java",
        ".md", ".tex", ".txt",
    },
    "Config": {
        ".json", ".yaml", ".yml", ".toml",
        ".ini", ".cfg",
    },
}


# ----------------------------------------------------------------------
# Convert a byte count into something easier to read.
#
# Example:
#
#     1250000 -> "1.25 MB"
# ----------------------------------------------------------------------

def human_size(num_bytes):
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)

    for unit in units:
        if size < 1000 or unit == units[-1]:
            return f"{size:,.2f} {unit}"

        size /= 1000


# ----------------------------------------------------------------------
# Determine which category a file belongs to from its extension.
# ----------------------------------------------------------------------

def category_for(path):
    suffix = path.suffix.lower()

    for category, extensions in CATEGORIES.items():
        if suffix in extensions:
            return category

    return "Other"


# ----------------------------------------------------------------------
# Convert GitHub ISO timestamps into datetime objects.
#
# GitHub normally returns times such as:
#
#     2026-08-14T03:21:42Z
# ----------------------------------------------------------------------

def github_datetime(value):
    if not value:
        return None

    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


# ----------------------------------------------------------------------
# Format a GitHub date for the report.
# ----------------------------------------------------------------------

def format_date(value):
    dt = github_datetime(value)

    if not dt:
        return "Unknown"

    return dt.strftime("%Y-%m-%d")


# ----------------------------------------------------------------------
# Return the number of days since a GitHub timestamp.
# ----------------------------------------------------------------------

def days_since(value):
    dt = github_datetime(value)

    if not dt:
        return None

    now = datetime.now(timezone.utc)

    return (now - dt).days


# ----------------------------------------------------------------------
# Give a repository a simple activity classification based on its
# most recent push.
# ----------------------------------------------------------------------

def activity_status(repo_info):
    if repo_info.get("archived"):
        return "Archived"

    days = days_since(
        repo_info.get("pushed_at")
    )

    if days is None:
        return "Unknown"

    if days < 30:
        return "Active"

    if days < 90:
        return "Quiet"

    if days < 365:
        return "Dormant"

    return "Stale"


# ----------------------------------------------------------------------
# Retrieve our GitHub Personal Access Token from macOS Keychain.
#
# The token was stored under the service name:
#
#     github-api-token
#
# This keeps the token out of the source code and shell history.
# ----------------------------------------------------------------------

def get_github_token():
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a", os.environ["USER"],
                "-s", "github-api-token",
                "-w",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    except subprocess.CalledProcessError:
        print(
            "Error: Could not retrieve GitHub token "
            "from macOS Keychain."
        )
        sys.exit(1)

    token = result.stdout.strip()

    if not token:
        print(
            "Error: GitHub token in Keychain is empty."
        )
        sys.exit(1)

    return token


# ----------------------------------------------------------------------
# Retrieve the token ONCE.
#
# github_api() may be called many times while producing a report.
# There is no reason to ask Keychain for the same token repeatedly.
# ----------------------------------------------------------------------

GITHUB_TOKEN = get_github_token()


# ----------------------------------------------------------------------
# Make a request to the GitHub REST API.
#
# return_headers=True is useful when we want to inspect GitHub's
# pagination Link header.
#
# allow_404=True allows optional things such as releases to fail cleanly.
# ----------------------------------------------------------------------

def github_api(
    endpoint,
    return_headers=False,
    allow_404=False
):
    url = f"https://api.github.com{endpoint}"

    request = urllib.request.Request(
        url,
        headers={
            "Authorization":
                f"Bearer {GITHUB_TOKEN}",

            "Accept":
                "application/vnd.github+json",

            "X-GitHub-Api-Version":
                "2022-11-28",

            "User-Agent":
                "synaptech-github-report",
        },
    )

    try:
        with urllib.request.urlopen(request) as response:
            data = json.load(response)

            if return_headers:
                return data, response.headers

            return data

    except urllib.error.HTTPError as error:

        if allow_404 and error.code == 404:
            if return_headers:
                return None, None

            return None

        print(
            f"GitHub API error: "
            f"{error.code} {error.reason}"
        )

        print(f"Endpoint: {endpoint}")

        sys.exit(1)

    except urllib.error.URLError as error:
        print(
            f"Network error: "
            f"{error.reason}"
        )

        sys.exit(1)


# ----------------------------------------------------------------------
# Count objects returned by a paginated GitHub endpoint without
# downloading every object.
#
# We request only ONE object per page:
#
#     per_page=1
#
# GitHub's Link header will then tell us the number of the last page.
# Since each page contains one object:
#
#     last page number == object count
#
# This is much cheaper than downloading hundreds or thousands of
# commits merely to count them.
# ----------------------------------------------------------------------

def github_count(endpoint):

    separator = "&" if "?" in endpoint else "?"

    data, headers = github_api(
        f"{endpoint}{separator}per_page=1",
        return_headers=True,
    )

    if not data:
        return 0

    link = headers.get("Link", "")

    match = re.search(
        r'[?&]page=(\d+)[^>]*>;\s*rel="last"',
        link
    )

    if match:
        return int(match.group(1))

    # If there is no "last" link, everything fitted on the first page.
    return len(data)


# ----------------------------------------------------------------------
# Get basic repository information.
#
# This one API response already gives us quite a lot:
#
#     description
#     visibility
#     created date
#     pushed date
#     stars
#     forks
#     issues
#     licence
#     default branch
#     primary language
#     archived status
#     Pages status
#     etc.
# ----------------------------------------------------------------------

repo_info = github_api(
    f"/repos/{REPO}"
)

default_branch = repo_info["default_branch"]


# ----------------------------------------------------------------------
# Gather additional repository statistics.
# ----------------------------------------------------------------------

print()
print(f"Reading GitHub data for {REPO}...")


# Open pull requests.
open_prs = github_count(
    f"/repos/{REPO}/pulls?state=open"
)


# GitHub's open_issues_count includes pull requests.
#
# Therefore:
#
#     real issues = GitHub issue count - open PR count
#
# Do not allow a strange API result to produce a negative count.
open_issues = max(
    repo_info.get("open_issues_count", 0)
    - open_prs,
    0
)


# Branch count.
branch_count = github_count(
    f"/repos/{REPO}/branches"
)


# Tag count.
tag_count = github_count(
    f"/repos/{REPO}/tags"
)


# Contributor count.
contributor_count = github_count(
    f"/repos/{REPO}/contributors"
)


# Number of commits reachable from the default branch.
#
# sha=default_branch makes the meaning of the count explicit.
quoted_branch = urllib.parse.quote(
    default_branch,
    safe=""
)

commit_count = github_count(
    f"/repos/{REPO}/commits?sha={quoted_branch}"
)


# Number of releases.
release_count = github_count(
    f"/repos/{REPO}/releases"
)


# ----------------------------------------------------------------------
# Get latest release.
#
# The releases endpoint returns newest releases first, so requesting
# one result gives us the latest release if one exists.
# ----------------------------------------------------------------------

latest_releases = github_api(
    f"/repos/{REPO}/releases?per_page=1"
)

latest_release = (
    latest_releases[0]
    if latest_releases
    else None
)


# ----------------------------------------------------------------------
# Get GitHub's language analysis.
#
# GitHub returns the number of bytes attributed to each language:
#
#     {
#         "Python": 12345,
#         "C": 4567
#     }
# ----------------------------------------------------------------------

languages = github_api(
    f"/repos/{REPO}/languages"
)

language_total = sum(
    languages.values()
)


# ----------------------------------------------------------------------
# Ask GitHub for the complete Git tree for the default branch.
#
# recursive=1 tells GitHub to return the entire directory tree rather
# than only the repository root.
# ----------------------------------------------------------------------

tree_data = github_api(
    f"/repos/{REPO}/git/trees/"
    f"{quoted_branch}?recursive=1"
)


# GitHub can truncate extremely large recursive trees.
#
# Silently producing a partial storage report would be misleading,
# so stop if that ever happens.
if tree_data.get("truncated"):
    print(
        "Error: GitHub truncated the repository tree."
    )

    print(
        "The repository is too large for a single "
        "recursive tree request."
    )

    sys.exit(1)


# ----------------------------------------------------------------------
# Build our file list.
#
# Each Git blob corresponds to a tracked file.
#
# Each entry in files is stored as:
#
#     (path, size)
# ----------------------------------------------------------------------

files = []

for item in tree_data["tree"]:

    # Ignore directories and other Git objects.
    if item["type"] != "blob":
        continue

    path = PurePosixPath(
        item["path"]
    )

    # Ignore unwanted directories.
    if any(
        part in IGNORE_DIRS
        for part in path.parts
    ):
        continue

    size = item.get(
        "size",
        0
    )

    files.append(
        (path, size)
    )


# ----------------------------------------------------------------------
# Calculate storage totals by file category.
# ----------------------------------------------------------------------

totals = defaultdict(int)

for path, size in files:
    totals[category_for(path)] += size


total_size = sum(
    size
    for _, size in files
)


percentage = (
    total_size
    / PAGES_LIMIT
    * 100
)


# ----------------------------------------------------------------------
# Additional metadata for display.
# ----------------------------------------------------------------------

description = (
    repo_info.get("description")
    or "None"
)

visibility = (
    repo_info.get("visibility")
    or (
        "private"
        if repo_info.get("private")
        else "public"
    )
)

primary_language = (
    repo_info.get("language")
    or "None"
)

license_info = repo_info.get("license")

if license_info:
    license_name = (
        license_info.get("spdx_id")
        or license_info.get("name")
        or "Unknown"
    )
else:
    license_name = "None"


created_days = days_since(
    repo_info.get("created_at")
)

pushed_days = days_since(
    repo_info.get("pushed_at")
)


# Actual repository subscribers / watchers.
#
# Do NOT use watchers_count here because GitHub historically aliases
# watchers_count to stars.
watchers = repo_info.get(
    "subscribers_count",
    0
)


# ----------------------------------------------------------------------
# Print report
# ----------------------------------------------------------------------

print()
print("SYNAPTECH LABS — REPOSITORY REPORT")
print("=" * 56)
print()


# ----------------------------------------------------------------------
# Repository information
# ----------------------------------------------------------------------

print("REPOSITORY")
print("-" * 56)

print(f"Repository:          {REPO}")
print(f"Description:         {description}")
print(f"Visibility:          {visibility.title()}")
print(f"Default branch:      {default_branch}")
print(f"Primary language:    {primary_language}")
print(f"License:             {license_name}")

print(
    f"Fork:                "
    f"{'Yes' if repo_info.get('fork') else 'No'}"
)

print(
    f"Archived:            "
    f"{'Yes' if repo_info.get('archived') else 'No'}"
)

print(
    f"GitHub Pages:        "
    f"{'Enabled' if repo_info.get('has_pages') else 'No'}"
)

print()


# ----------------------------------------------------------------------
# Repository age and activity
# ----------------------------------------------------------------------

print("ACTIVITY")
print("-" * 56)

print(
    f"Created:             "
    f"{format_date(repo_info.get('created_at'))}"
)

if created_days is not None:
    print(
        f"Repository age:      "
        f"{created_days:,} days"
    )

print(
    f"Last push:           "
    f"{format_date(repo_info.get('pushed_at'))}"
)

if pushed_days is not None:
    print(
        f"Days since push:     "
        f"{pushed_days:,}"
    )

print(
    f"Activity status:     "
    f"{activity_status(repo_info)}"
)

print()


# ----------------------------------------------------------------------
# GitHub activity statistics
# ----------------------------------------------------------------------

print("GITHUB STATISTICS")
print("-" * 56)

print(
    f"Stars:               "
    f"{repo_info.get('stargazers_count', 0):,}"
)

print(
    f"Watchers:            "
    f"{watchers:,}"
)

print(
    f"Forks:               "
    f"{repo_info.get('forks_count', 0):,}"
)

print(
    f"Open issues:         "
    f"{open_issues:,}"
)

print(
    f"Open pull requests:  "
    f"{open_prs:,}"
)

print(
    f"Commits:             "
    f"{commit_count:,}"
)

print(
    f"Branches:            "
    f"{branch_count:,}"
)

print(
    f"Tags:                "
    f"{tag_count:,}"
)

print(
    f"Contributors:        "
    f"{contributor_count:,}"
)

print(
    f"Releases:            "
    f"{release_count:,}"
)

if latest_release:

    release_name = (
        latest_release.get("name")
        or latest_release.get("tag_name")
        or "Unnamed"
    )

    release_date = (
        latest_release.get("published_at")
        or latest_release.get("created_at")
    )

    print(
        f"Latest release:      "
        f"{release_name}"
    )

    print(
        f"Release date:        "
        f"{format_date(release_date)}"
    )

else:
    print(
        f"Latest release:      None"
    )

print()


# ----------------------------------------------------------------------
# GitHub language analysis
# ----------------------------------------------------------------------

print("LANGUAGES")
print("-" * 56)

if languages:

    for language, size in sorted(
        languages.items(),
        key=lambda item: item[1],
        reverse=True
    ):

        pct = (
            size / language_total * 100
            if language_total
            else 0
        )

        print(
            f"{language:<20}"
            f"{human_size(size):>14}"
            f"{pct:>9.1f}%"
        )

else:
    print("No language data available.")

print()


# ----------------------------------------------------------------------
# Storage summary
# ----------------------------------------------------------------------

print("STORAGE")
print("-" * 56)

print(
    f"Files:               "
    f"{len(files):,}"
)

print(
    f"Tracked file size:   "
    f"{human_size(total_size)}"
)

# GitHub repository size is reported by the repository API in KB.
github_repo_size = (
    repo_info.get("size", 0)
    * 1000
)

print(
    f"GitHub repo size:    "
    f"{human_size(github_repo_size)}"
)

print(
    f"GitHub Pages limit:  "
    f"{human_size(PAGES_LIMIT)}"
)

print(
    f"Limit used:          "
    f"{percentage:.1f}%"
)

print()


# ----------------------------------------------------------------------
# Storage by file type
# ----------------------------------------------------------------------

print("BY FILE TYPE")
print("-" * 56)

for category, size in sorted(
    totals.items(),
    key=lambda item: item[1],
    reverse=True
):

    pct = (
        size / total_size * 100
        if total_size
        else 0
    )

    print(
        f"{category:<20}"
        f"{human_size(size):>14}"
        f"{pct:>9.1f}%"
    )


# ----------------------------------------------------------------------
# Largest files
# ----------------------------------------------------------------------

print()
print("20 LARGEST FILES")
print("-" * 56)

for path, size in sorted(
    files,
    key=lambda item: item[1],
    reverse=True
)[:20]:

    print(
        f"{human_size(size):>12}  "
        f"{path}"
    )


# ----------------------------------------------------------------------
# GitHub Pages storage status
# ----------------------------------------------------------------------

print()

if percentage < 50:
    status = "Plenty of headroom."

elif percentage < 70:
    status = "Healthy, but worth watching."

elif percentage < 85:
    status = "Start planning large-file offloading."

elif percentage < 95:
    status = "Approaching the GitHub Pages limit."

else:
    status = "Very close to the GitHub Pages limit."


print(f"STORAGE STATUS: {status}")
print()
