import { createServer } from 'node:http';

createServer((_, response) => {
  response.writeHead(302, { Location: 'http://localhost:5173' });
  response.end();
}).listen(4173, () => console.log('AI Office moved to http://localhost:5173'));
