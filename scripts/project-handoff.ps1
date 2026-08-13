[CmdletBinding()]
param(
    [ValidateSet('Validate', 'Resume', 'Create')]
    [string]$Mode = 'Validate',
    [string]$RepositoryPath = '.',
    [string]$TaskName,
    [string]$WorktreePath,
    [switch]$SkipFetch,
    [Parameter(DontShow)]
    [switch]$TestFailAfterCreate
)

$ErrorActionPreference = 'Stop'
$issueFileName = ([char]0x95EE) + ([char]0x9898) + ([char]0x8BB0) + ([char]0x5F55) + '.md'
$governanceFiles = @(
    'AGENTS.md',
    'docs/system-maintainer-onboarding-guide.md',
    ('docs/' + $issueFileName)
)

function Invoke-GitText {
    param([string]$Path, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $output = & git -C $Path @Arguments
    if ($LASTEXITCODE -ne 0) { throw "git failed in ${Path}: $($Arguments -join ' ')" }
    return @($output)
}

function Test-Worktree {
    param([string]$Path, [bool]$FetchRemote, [bool]$Strict)

    $root = @(Invoke-GitText $Path rev-parse --show-toplevel)[0]
    if ($FetchRemote) { Invoke-GitText $root fetch origin | Out-Null }

    $branch = @(Invoke-GitText $root branch --show-current)[0]
    if ([string]::IsNullOrWhiteSpace($branch)) { throw 'Detached HEAD is not allowed for a task worktree' }

    foreach ($file in $governanceFiles) {
        Invoke-GitText $root ls-files --error-unmatch -- $file | Out-Null
        if (-not (Test-Path -LiteralPath (Join-Path $root $file))) { throw "Missing governance file: $file" }
    }

    $status = Invoke-GitText $root status --porcelain
    if ($Strict -and $status.Count -ne 0) { throw "Worktree is not clean: $($status -join '; ')" }

    $head = @(Invoke-GitText $root rev-parse HEAD)[0]
    $master = @(Invoke-GitText $root rev-parse origin/master)[0]
    $counts = (@(Invoke-GitText $root rev-list --left-right --count 'origin/master...HEAD')[0] -split '\s+')
    if ($counts.Count -ne 2) { throw 'Unable to determine ahead/behind state' }
    $behind = [int]$counts[0]
    $ahead = [int]$counts[1]
    if ($Strict -and $behind -ne 0) { throw "Worktree is behind origin/master by $behind commit(s)" }

    $governanceMatches = $true
    foreach ($file in $governanceFiles) {
        & git -C $root diff --quiet origin/master -- $file
        if ($LASTEXITCODE -ne 0) {
            $governanceMatches = $false
            if ($Strict) { throw "Governance file differs from origin/master: $file" }
        }
    }

    [pscustomobject]@{
        RepositoryRoot = $root
        WorktreePath = $root
        Branch = $branch
        Head = $head
        OriginMaster = $master
        Behind = $behind
        Ahead = $ahead
        Clean = ($status.Count -eq 0)
        GovernanceFilesTracked = $true
        GovernanceFilesMatchMaster = $governanceMatches
        StrictGatePassed = ($Strict -and $status.Count -eq 0 -and $behind -eq 0 -and $governanceMatches)
        ProductionWritesAuthorized = $false
    }
}

$repositoryRoot = @(Invoke-GitText $RepositoryPath rev-parse --show-toplevel)[0]

if ($Mode -eq 'Create') {
    if ([string]::IsNullOrWhiteSpace($TaskName) -or $TaskName -notmatch '^[a-z0-9][a-z0-9._-]*$') {
        throw 'TaskName must use lowercase letters, digits, dot, underscore, or hyphen'
    }
    if ([string]::IsNullOrWhiteSpace($WorktreePath)) { throw 'WorktreePath is required in Create mode' }
    if (-not [System.IO.Path]::IsPathRooted($WorktreePath)) { throw 'WorktreePath must be absolute' }
    $normalizedPath = [System.IO.Path]::GetFullPath($WorktreePath)
    if ($normalizedPath -eq [System.IO.Path]::GetFullPath($repositoryRoot)) { throw 'WorktreePath must differ from the repository root' }
    if (Test-Path -LiteralPath $normalizedPath) { throw "WorktreePath already exists: $normalizedPath" }
    if (-not $SkipFetch) { Invoke-GitText $repositoryRoot fetch origin | Out-Null }
    $branchName = "codex/$TaskName"
    & git -C $repositoryRoot show-ref --verify --quiet "refs/heads/$branchName" 2>$null
    if ($LASTEXITCODE -eq 0) { throw "Branch already exists: $branchName" }
    if ($LASTEXITCODE -ne 1) { throw 'Unable to verify target branch' }
    $masterBefore = @(Invoke-GitText $repositoryRoot rev-parse origin/master)[0]
    $created = $false
    try {
        & git -C $repositoryRoot worktree add -b $branchName $normalizedPath $masterBefore
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create worktree' }
        $created = $true
        if ($TestFailAfterCreate) { throw 'Injected failure after worktree creation' }
        $result = Test-Worktree -Path $normalizedPath -FetchRemote $false -Strict $true
        if ($result.Head -ne $masterBefore -or $result.OriginMaster -ne $masterBefore) { throw 'origin/master changed during worktree creation' }
        $result
    }
    catch {
        $originalError = $_
        if ($created) {
            & git -C $repositoryRoot worktree remove --force $normalizedPath 2>$null
            $removeExit = $LASTEXITCODE
            & git -C $repositoryRoot branch -D -- $branchName 2>$null
            $branchExit = $LASTEXITCODE
            if ($removeExit -ne 0 -or $branchExit -ne 0) {
                throw "Create failed: $originalError; cleanup failed (worktree=$removeExit branch=$branchExit)"
            }
        }
        throw $originalError
    }
}
elseif ($Mode -eq 'Resume') {
    Test-Worktree -Path $repositoryRoot -FetchRemote (-not $SkipFetch) -Strict $false
}
else {
    Test-Worktree -Path $repositoryRoot -FetchRemote (-not $SkipFetch) -Strict $true
}
