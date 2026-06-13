export function CopyButton({ value, label = "复制" }: { value: string; label?: string }) {
  const handleClick = async () => {
    await navigator.clipboard.writeText(value);
  };

  return (
    <button type="button" className="secondary-button" onClick={handleClick}>
      {label}
    </button>
  );
}

