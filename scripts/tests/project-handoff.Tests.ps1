$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'project-handoff.ps1'
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Missing handoff script: $scriptPath"
}

function Invoke-Git {
    param([string]$Path, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & git -C $Path @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "git failed in ${Path}: $($Arguments -join ' ')" }
}

function Invoke-Handoff {
    param([string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & powershell -NoProfile -ExecutionPolicy Bypass -File $scriptPath @Arguments 2>$null | Out-Null
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
    return $exitCode
}

function Invoke-HandoffOutput {
    param([string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $scriptPath @Arguments 2>$null | Out-String
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
    return [pscustomobject]@{ ExitCode = $exitCode; Output = $output }
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("adx-handoff-test-" + [guid]::NewGuid().ToString('N'))
$remote = Join-Path $tempRoot 'remote.git'
$seed = Join-Path $tempRoot 'seed'
$worktree = Join-Path $tempRoot 'created'
$issueFileName = ([char]0x95EE) + ([char]0x9898) + ([char]0x8BB0) + ([char]0x5F55) + '.md'
$issuePath = Join-Path $seed ('docs/' + $issueFileName)

try {
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    & git init --bare $remote | Out-Null
    & git init -b master $seed | Out-Null
    Invoke-Git $seed config user.email 'test@example.invalid'
    Invoke-Git $seed config user.name 'Handoff Test'
    New-Item -ItemType Directory -Path (Join-Path $seed 'docs') | Out-Null
    Set-Content -Encoding utf8 (Join-Path $seed 'AGENTS.md') '# rules'
    Set-Content -Encoding utf8 (Join-Path $seed 'docs/system-maintainer-onboarding-guide.md') '# guide'
    Set-Content -Encoding utf8 $issuePath '# issues'
    Invoke-Git $seed add -- AGENTS.md docs/system-maintainer-onboarding-guide.md ('docs/' + $issueFileName)
    Invoke-Git $seed commit -m baseline
    Invoke-Git $seed remote add origin $remote
    Invoke-Git $seed push -u origin master

    if ((Invoke-Handoff @('-Mode','Validate','-RepositoryPath',$seed,'-SkipFetch')) -ne 0) { throw 'Validate should accept a clean tracked baseline' }
    $validateOutput = Invoke-HandoffOutput @('-Mode','Validate','-RepositoryPath',$seed,'-SkipFetch')
    if ($validateOutput.Output -notmatch 'StrictGatePassed\s+: True') { throw 'Validate should report that the strict local gate passed' }
    if ($validateOutput.Output -notmatch 'ProductionWritesAuthorized\s+: False') { throw 'Validate must never authorize production writes' }

    Set-Content -Encoding utf8 (Join-Path $seed 'dirty.tmp') 'dirty'
    if ((Invoke-Handoff @('-Mode','Validate','-RepositoryPath',$seed,'-SkipFetch')) -eq 0) { throw 'Validate should reject a dirty worktree' }
    if ((Invoke-Handoff @('-Mode','Resume','-RepositoryPath',$seed,'-SkipFetch')) -ne 0) { throw 'Resume should report a dirty existing task without modifying it' }
    $resumeOutput = Invoke-HandoffOutput @('-Mode','Resume','-RepositoryPath',$seed,'-SkipFetch')
    if ($resumeOutput.Output -notmatch 'StrictGatePassed\s+: False') { throw 'Resume should not claim the strict local gate passed' }
    if ($resumeOutput.Output -notmatch 'ProductionWritesAuthorized\s+: False') { throw 'Resume must never authorize production writes' }
    Remove-Item -LiteralPath (Join-Path $seed 'dirty.tmp')

    $other = Join-Path $tempRoot 'other'
    & git clone $remote $other | Out-Null
    Invoke-Git $other config user.email 'test@example.invalid'
    Invoke-Git $other config user.name 'Handoff Test'
    Set-Content -Encoding utf8 (Join-Path $other 'advance.tmp') 'advance'
    Invoke-Git $other add -- advance.tmp
    Invoke-Git $other commit -m advance
    Invoke-Git $other push origin master
    Invoke-Git $seed fetch origin
    if ((Invoke-Handoff @('-Mode','Validate','-RepositoryPath',$seed,'-SkipFetch')) -eq 0) { throw 'Validate should reject a branch behind origin/master' }
    Invoke-Git $seed merge --ff-only origin/master

    Invoke-Git $seed rm -- ('docs/' + $issueFileName)
    Invoke-Git $seed commit -m remove-issues
    if ((Invoke-Handoff @('-Mode','Validate','-RepositoryPath',$seed,'-SkipFetch')) -eq 0) { throw 'Validate should reject a missing governance file' }
    Invoke-Git $seed reset --hard 'HEAD^'

    if ((Invoke-Handoff @('-Mode','Create','-RepositoryPath',$seed,'-TaskName','sample-task','-WorktreePath',$worktree)) -ne 0) { throw 'Create should create and validate a worktree' }
    if ((& git -C $worktree branch --show-current) -ne 'codex/sample-task') { throw 'Unexpected created branch' }
    $createOutput = Invoke-HandoffOutput @('-Mode','Validate','-RepositoryPath',$worktree,'-SkipFetch')
    if ($createOutput.Output -notmatch 'ProductionWritesAuthorized\s+: False') { throw 'Created worktrees must never be granted production writes' }
    if ((Invoke-Handoff @('-Mode','Validate','-RepositoryPath',$worktree,'-SkipFetch')) -ne 0) { throw 'Created worktree should validate' }

    $rollbackPath = Join-Path $tempRoot 'rollback-created'
    if ((Invoke-Handoff @('-Mode','Create','-RepositoryPath',$seed,'-TaskName','rollback-task','-WorktreePath',$rollbackPath,'-SkipFetch','-TestFailAfterCreate')) -eq 0) { throw 'Injected Create failure should fail' }
    if (Test-Path -LiteralPath $rollbackPath) { throw 'Failed Create should remove its worktree' }
    & git -C $seed show-ref --verify --quiet refs/heads/codex/rollback-task
    if ($LASTEXITCODE -eq 0) { throw 'Failed Create should remove its branch' }

    if ((Invoke-Handoff @('-Mode','Create','-RepositoryPath',$seed,'-TaskName','relative-task','-WorktreePath','relative-path','-SkipFetch')) -eq 0) { throw 'Create should reject relative paths' }

    Write-Output 'PASS project-handoff tests'
}
finally {
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
}
