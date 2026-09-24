<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');

$token = $_GET['token'] ?? '';
$accountKey = $_GET['account_key'] ?? '';
$reportDate = $_GET['report_date'] ?? '';
$expectedToken = getenv('ADX_TRIGGER_TOKEN') ?: '';
$fetchApiBaseUrl = rtrim(getenv('ADX_FETCH_API_BASE_URL') ?: 'http://127.0.0.1:9100', '/');

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

$parsedDate = DateTimeImmutable::createFromFormat('!Y-m-d', $reportDate);
if ($parsedDate === false || $parsedDate->format('Y-m-d') !== $reportDate) {
    http_response_code(400);
    echo json_encode([
        'ok' => false,
        'error_code' => 'REQUEST_ERROR',
        'message' => 'report_date must be YYYY-MM-DD',
    ], JSON_UNESCAPED_SLASHES);
    exit;
}

if (strlen($accountKey) > 100) {
    http_response_code(400);
    echo json_encode([
        'ok' => false,
        'error_code' => 'REQUEST_ERROR',
        'message' => 'account_key is too long',
    ], JSON_UNESCAPED_SLASHES);
    exit;
}

$requestId = 'req_' . gmdate('Ymd_His') . '_' . bin2hex(random_bytes(4));
$query = http_build_query([
    'account_key' => $accountKey,
    'report_date' => $reportDate,
]);

$ch = curl_init($fetchApiBaseUrl . '/internal/reports/site-daily?' . $query);
if ($ch === false) {
    http_response_code(500);
    echo json_encode([
        'ok' => false,
        'request_id' => $requestId,
        'error_code' => 'FETCH_ERROR',
        'message' => 'failed to initialize curl',
    ], JSON_UNESCAPED_SLASHES);
    exit;
}

curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 30,
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
$decodedBody = json_decode($body, true);
if (is_array($decodedBody) && !array_key_exists('request_id', $decodedBody)) {
    $decodedBody['request_id'] = $requestId;
    echo json_encode($decodedBody, JSON_UNESCAPED_SLASHES);
    exit;
}

echo $body;
