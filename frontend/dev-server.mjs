import { createServer } from "node:http";
import { readFile } from "node:fs/promises";

const pageUrl = new URL("./index.html", import.meta.url);

const server = createServer(async (_request, response) => {
  try {
    const page = await readFile(pageUrl);
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end(page);
  } catch {
    response.writeHead(500);
    response.end();
  }
});

server.listen(5173, "0.0.0.0");
