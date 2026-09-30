import { useIsAdmin } from '../../app';
import { Banner, Card, ChannelStatus, Switch } from '../../components/ds';
import type { Workspace } from '../ClassWorkspace';

export default function DeliveryTab({ ws, patch, busy }: { ws: Workspace; patch: (b: Partial<Workspace>) => void; busy: boolean }) {
  const admin = useIsAdmin();
  const phase2 = ws.phase >= 2;
  return <>
    <Card title="How worksheets are sent">
      <div className="stack">
        <Switch on={ws.channel_email} disabled={!admin || busy} label="Email" description="Phase 1. The worksheet PDF is attached to an email for each student."
          onChange={(v) => patch({ channel_email: v })} />
        <Switch on={ws.channel_whatsapp} disabled={!admin || busy || !phase2} label="WhatsApp"
          description={phase2 ? 'Phase 2. The same worksheet version is sent as a document. Tracked separately from email.' : 'Available in Phase 2. An administrator turns Phase 2 on in Settings.'}
          onChange={(v) => patch({ channel_whatsapp: v })} />
      </div>
    </Card>
    <div className="grid-2">
      <ChannelStatus channel="email" status={ws.channel_email ? 'active' : 'paused'} detail={ws.channel_email ? 'Sends to every active student with a valid address' : 'Turned off for this class'} />
      <ChannelStatus channel="whatsapp" status={phase2 ? (ws.channel_whatsapp ? 'active' : 'paused') : 'off'}
        detail={phase2 ? (ws.channel_whatsapp ? 'Students without a number are skipped and logged' : 'Turned off for this class') : 'Turns on in Phase 2'} phase="Phase 2" />
    </div>
    <Banner>A successful email never counts as a WhatsApp delivery. Each channel has its own status per student in the Delivery monitor.</Banner>
  </>;
}
