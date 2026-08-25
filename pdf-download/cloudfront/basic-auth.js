function handler(event) {
  var request = event.request;
  var uri = request.uri || "/";
  if (_isPublicApi(uri)) {
    return request;
  }

  var allowed = {
    "Basic ZXNtaWxlOm9zYWth": true,
    "Basic ZW5nYXdhOlNVU1VLSU5P": true
  };
  var auth = request.headers.authorization && request.headers.authorization.value;
  if (auth && allowed[auth]) {
    return request;
  }

  return {
    statusCode: 401,
    statusDescription: "Unauthorized",
    headers: {
      "www-authenticate": { value: 'Basic realm="esmile009"' },
      "cache-control": { value: "no-store" }
    },
    body: "Authentication required"
  };
}

function _isPublicApi(uri) {
  return (
    uri === "/health" ||
    uri.indexOf("/convert") === 0 ||
    uri.indexOf("/jobs") === 0 ||
    uri.indexOf("/docs") === 0 ||
    uri.indexOf("/openapi") === 0
  );
}
