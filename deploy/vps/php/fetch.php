<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');

$token = $_GET['token'] ?? '';
$accountKey = $_GET['account_key'] ?? '';
$reportDate = $_GET['report_date'] ?? '';
$expectedToken = getenv('ADX_TRIGGER_TOKEN') ?: '';

if ($expectedToken === '' || !hash_equals($expectedToken, $token)) {
    http_response_code(401);
    echo json_encode([
        'ok' => false,
        'error_code' => 'REQUEST_ERROR',
        'message' => 'invalid token',
    ], JSON_UNESCAPED_SLASHES);
    exit;
}

if ($accountKey === '' || $reportDate === '') {
    http_response_code(400);
    echo json_encode([
        'ok' => false,
        'error_code' => 'REQUEST_ERROR',
        'message' => 'missing account_key or report_date',
    ], JSON_UNESCAPED_SLASHES);
    exit;
}

$requestId = 'req_' . gmdate('Ymd_His') . '_' . bin2hex(random_bytes(4));
$payload = json_encode([
    'account_key' => $accountKey,
    'report_date' => $reportDate,
    'trigger_source' => 'php_manual',
    'request_id' => $requestId,
], JSON_UNESCAPED_SLASHES);

if ($payload === false) {
    http_response_code(500);
    echo json_encode([
        'ok' => false,
        'request_id' => $requestId,
        'error_code' => 'REQUEST_ERROR',
        'message' => 'failed to encode request payload',
    ], JSON_UNESCAPED_SLASHES);
    exit;
}

$ch = curl_init('http://127.0.0.1:9100/internal/fetch');
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
    CURLOPT_POSTFIELDS => $payload,
    CURLOPT_TIMEOUT => 120,
]);

$body = curl_exec($ch);
$status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
$error = curl_error($ch);
curl_close($ch);

if ($body === false) {
    http_response_code(502);
    echo json_encode([
        'ok' => false,
        'request_id' => $requestId,
        'error_code' => 'FETCH_ERROR',
        'message' => $error,
    ], JSON_UNESCAPED_SLASHES);
    exit;
}

http_response_code($status > 0 ? $status : 502);
echo $body;
