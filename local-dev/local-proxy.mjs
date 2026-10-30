// Local Docker Desktop ingress only. Fixed upstream; no arbitrary URL forwarding.
import http from 'node:http';
const server = http.createServer((request, response) => {
  if (!request.url?.startsWith('/') || request.method === 'CONNECT') {
    response.writeHead(400).end('Invalid local request');
    return;
  }
  const upstream = http.request({
    hostname: 'app', port: 8080, method: request.method,
    path: request.url, headers: request.headers,
  }, incoming => {
    response.writeHead(incoming.statusCode, incoming.headers);
    incoming.pipe(response);
    incoming.on('error', () => response.destroy());
  });
  upstream.setTimeout(30000, () => upstream.destroy());
  upstream.on('error', () => {
    if (!response.headersSent) response.writeHead(502);
    response.end('Local application unavailable');
  });
  request.on('aborted', () => upstream.destroy());
  request.on('error', () => upstream.destroy());
  request.pipe(upstream);
});
server.requestTimeout = 60000;
server.headersTimeout = 15000;
server.on('connect', (_request, socket) => socket.end('HTTP/1.1 405 Method Not Allowed\r\n\r\n'));
server.on('upgrade', (_request, socket) => socket.end('HTTP/1.1 400 Bad Request\r\n\r\n'));
server.listen(8080, '0.0.0.0', () => console.log('Local fixed-upstream proxy ready'));
