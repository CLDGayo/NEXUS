import HealthBadge from './HealthBadge.jsx';
import WorkspaceSwitcher from '../tenant/WorkspaceSwitcher.jsx';

export default function PageHeader({ title, right }) {
  return (
    <header className="flex items-center justify-between border-b border-nexus-border bg-white px-6 py-3">
      <h1 className="text-base font-semibold tracking-tight">{title}</h1>
      <div className="flex items-center gap-3">
        {right}
        <WorkspaceSwitcher />
        <HealthBadge />
      </div>
    </header>
  );
}
