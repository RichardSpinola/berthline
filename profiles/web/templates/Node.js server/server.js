import { createServer } from 'node:http';

const port = 3000;

const server = createServer((req, res) => {
  res.writeHead(200, { 'content-type': 'application/json' });
  res.end(JSON.stringify({ message: 'Hello, World!', path: req.url }));
});

server.listen(port, '127.0.0.1', () => {
  console.log(`Server running at http://localhost:${port}/`);
});
