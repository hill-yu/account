<?php
declare(strict_types=1);

date_default_timezone_set('UTC');

$state = trim((string) ($_GET['state'] ?? ''));
$code = trim((string) ($_GET['code'] ?? ''));
$scope = trim((string) ($_GET['scope'] ?? ''));
$issuer = trim((string) ($_GET['iss'] ?? ''));
$error = trim((string) ($_GET['error'] ?? ''));

if ($state === '' || $code === '') {
    http_response_code(400);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(
        [
            'ok' => false,
            'message' => 'missing state or code',
        ],
        JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
    );
    exit;
}

$scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
$host = (string) ($_SERVER['HTTP_HOST'] ?? 'localhost');
$path = (string) ($_SERVER['PHP_SELF'] ?? '/oauth/google/callback');
$redirectUri = rtrim($scheme . '://' . $host . $path, '/');

$callbackUrl = $redirectUri;
if (!empty($_SERVER['QUERY_STRING'])) {
    $callbackUrl .= '?' . (string) $_SERVER['QUERY_STRING'];
}

$downloadedAt = gmdate('c');
$filename = sprintf(
    'oauth-callback-%s-%s.json',
    preg_replace('/[^a-zA-Z0-9_-]+/', '-', $host),
    gmdate('Ymd-His')
);

$payload = [
    'state' => $state,
    'code' => $code,
    'redirect_uri' => $redirectUri,
    'callback_url' => $callbackUrl,
    'scope' => $scope !== '' ? $scope : null,
    'iss' => $issuer !== '' ? $issuer : null,
    'error' => $error !== '' ? $error : null,
    'downloaded_at' => $downloadedAt,
];

header('Content-Type: application/json; charset=utf-8');
header('Content-Disposition: attachment; filename="' . $filename . '"');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');

echo json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
