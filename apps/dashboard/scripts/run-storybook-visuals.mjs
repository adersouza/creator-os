#!/usr/bin/env node
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, "..", "storybook-static");
const port = Number(process.env.STORYBOOK_PORT || 6006);

const mime = new Map([
	[".css", "text/css; charset=utf-8"],
	[".html", "text/html; charset=utf-8"],
	[".js", "text/javascript; charset=utf-8"],
	[".json", "application/json; charset=utf-8"],
	[".svg", "image/svg+xml"],
	[".woff", "font/woff"],
	[".woff2", "font/woff2"],
]);

async function resolveFile(urlPath) {
	const decodedPath = decodeURIComponent(urlPath.split("?")[0] || "/");
	const safePath = path.normalize(decodedPath).replace(/^(\.\.[/\\])+/, "");
	const filePath = path.join(root, safePath === "/" ? "index.html" : safePath);
	const fileStat = await stat(filePath).catch(() => null);
	if (fileStat?.isFile()) return filePath;
	return path.join(root, "index.html");
}

const server = createServer(async (req, res) => {
	try {
		const filePath = await resolveFile(req.url || "/");
		const body = await readFile(filePath);
		res.writeHead(200, {
			"content-type": mime.get(path.extname(filePath)) || "application/octet-stream",
		});
		res.end(body);
	} catch {
		res.writeHead(404);
		res.end("Not found");
	}
});

server.listen(port, "127.0.0.1", () => {
	const child = spawn(
		"npx",
		["playwright", "test", "e2e/visual-regression.spec.ts", "--project=storybook"],
		{
			cwd: path.resolve(__dirname, ".."),
			env: { ...process.env },
			stdio: "inherit",
		},
	);
	child.on("exit", (code) => {
		server.close(() => process.exit(code ?? 1));
	});
});
