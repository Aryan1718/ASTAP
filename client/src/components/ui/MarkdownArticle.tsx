type MarkdownArticleProps = {
  content: string;
  className?: string;
};

type Block =
  | { type: "heading1"; text: string }
  | { type: "heading2"; text: string }
  | { type: "heading3"; text: string }
  | { type: "bullet"; items: string[] }
  | { type: "code"; lines: string[] }
  | { type: "paragraph"; text: string };

function tokenizeMarkdown(content: string): Block[] {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];

  let index = 0;
  while (index < lines.length) {
    const rawLine = lines[index];
    const line = rawLine.trim();

    if (!line) {
      index += 1;
      continue;
    }

    if (line.startsWith("```")) {
      index += 1;
      const codeLines: string[] = [];
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push({ type: "code", lines: codeLines });
      continue;
    }

    if (line.startsWith("# ")) {
      blocks.push({ type: "heading1", text: line.slice(2).trim() });
      index += 1;
      continue;
    }

    if (line.startsWith("## ")) {
      blocks.push({ type: "heading2", text: line.slice(3).trim() });
      index += 1;
      continue;
    }

    if (line.startsWith("### ")) {
      blocks.push({ type: "heading3", text: line.slice(4).trim() });
      index += 1;
      continue;
    }

    if (line.startsWith("- ")) {
      const items: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith("- ")) {
        items.push(lines[index].trim().slice(2).trim());
        index += 1;
      }
      blocks.push({ type: "bullet", items });
      continue;
    }

    const paragraphLines = [line];
    index += 1;
    while (index < lines.length) {
      const nextLine = lines[index].trim();
      if (!nextLine || nextLine.startsWith("#") || nextLine.startsWith("- ") || nextLine.startsWith("```")) {
        break;
      }
      paragraphLines.push(nextLine);
      index += 1;
    }

    blocks.push({ type: "paragraph", text: paragraphLines.join(" ") });
  }

  return blocks;
}

function renderInlineMarkdown(text: string) {
  const segments = text.split(/(`[^`]+`)/g);

  return segments.map((segment, index) => {
    if (segment.startsWith("`") && segment.endsWith("`") && segment.length >= 2) {
      return (
        <code
          key={`${segment}-${index}`}
          className="rounded bg-[#f7f3ee] px-1.5 py-0.5 font-mono text-[0.95em] text-ink"
        >
          {segment.slice(1, -1)}
        </code>
      );
    }

    return <span key={`${segment}-${index}`}>{segment}</span>;
  });
}

export function MarkdownArticle({ content, className }: MarkdownArticleProps) {
  const blocks = tokenizeMarkdown(content);

  return (
    <article className={className}>
      {blocks.map((block, index) => {
        if (block.type === "heading1") {
          return (
            <header key={`block-${index}`} className={index === 0 ? "" : "mt-10"}>
              <h1
                className="font-display text-[2rem] leading-[0.96] tracking-[-0.55px] text-ink md:text-[48px]"
                style={{ fontWeight: 460 }}
              >
                {block.text}
              </h1>
            </header>
          );
        }

        if (block.type === "heading2") {
          return (
            <section key={`block-${index}`} className="mt-8">
              <h2 className="font-display text-[26px] leading-[1.3] text-ink" style={{ fontWeight: 460 }}>
                {block.text}
              </h2>
            </section>
          );
        }

        if (block.type === "heading3") {
          return (
            <section key={`block-${index}`} className="mt-6">
              <h3 className="font-display text-xs uppercase tracking-[0.18em] text-muted" style={{ fontWeight: 600 }}>
                {block.text}
              </h3>
            </section>
          );
        }

        if (block.type === "bullet") {
          return (
            <ul key={`block-${index}`} className="mt-4 grid gap-3 pl-5 text-base leading-6 text-ink">
              {block.items.map((item, itemIndex) => (
                <li key={`bullet-${index}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>
              ))}
            </ul>
          );
        }

        if (block.type === "code") {
          return (
            <pre
              key={`block-${index}`}
              className="mt-5 overflow-x-auto rounded-2xl border border-line bg-[#fbf8f5] p-5 font-mono text-sm leading-6 text-ink"
            >
              {block.lines.join("\n")}
            </pre>
          );
        }

        return (
          <p key={`block-${index}`} className="mt-4 text-base leading-6 text-ink">
            {renderInlineMarkdown(block.text)}
          </p>
        );
      })}
    </article>
  );
}
