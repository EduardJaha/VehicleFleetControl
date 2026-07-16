type EntityPageHeaderProps = {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
};

export function EntityPageHeader({ title, description, actionLabel, onAction }: EntityPageHeaderProps) {
  return (
    <div className="header entityPageHeader">
      <div>
        <h1>{title}</h1>
        <p className="muted">{description}</p>
      </div>
      {actionLabel && onAction && (
        <button className="button entityPageAction" type="button" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}
