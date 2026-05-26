interface HtmlPreviewProps {
  content: string;
  fileName: string;
}

export function HtmlPreview({ content, fileName }: HtmlPreviewProps) {
  return (
    <iframe
      title={`Preview ${fileName}`}
      srcDoc={content}
      sandbox="allow-scripts"
      className="h-full w-full border-0 bg-white"
    />
  );
}
