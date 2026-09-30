import { useState } from 'react';
import { Button, Card } from '../../components/ds';
import type { Workspace } from '../ClassWorkspace';
import AutomationTab from './AutomationTab';
import DeliveryTab from './DeliveryTab';
import WorksheetSettingsTab from './WorksheetSettingsTab';

export default function SettingsTab({ ws, patch, busy, reload }: { ws: Workspace; patch: (b: Partial<Workspace>) => void; busy: boolean; reload: () => void }) {
  const [advanced, setAdvanced] = useState(false);
  return <>
    <WorksheetSettingsTab ws={ws} reload={reload} />
    <DeliveryTab ws={ws} patch={patch} busy={busy} />
    <Card title="Advanced" actions={<Button variant="quiet" size="sm" onClick={() => setAdvanced(!advanced)}>{advanced ? 'Hide' : 'Show'}</Button>}>
      {advanced ? <div className="stack-lg"><AutomationTab ws={ws} patch={patch} reload={reload} /></div>
        : <div className="muted-sm">How the daily schedule works, and a log of every worksheet job for this class.</div>}
    </Card>
  </>;
}
