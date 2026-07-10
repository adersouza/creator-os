export const metadata = {
  title: "ContentForge (headless)",
};

export default function Home() {
  return (
    <main style={{ fontFamily: "monospace", padding: "2rem" }}>
      <h1>contentforge headless ok</h1>
      <p>
        Browser UI removed. Service endpoints: <code>/api/similarity</code> and{" "}
        <code>/api/variant-pack</code>.
      </p>
    </main>
  );
}
