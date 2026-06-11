
import { MessageCircle, Bot } from 'lucide-react';
import { NovaCard } from '@/components/ui/NovaPrimitives';
import { Progress } from '@/components/ui/Progress';
import { Separator } from '@/components/ui/Separator';

export function ReplyChainStats() {
  const rows = [
    { label: "AI initiated threads", value: null, tone: "warn" as const, icon: true },
    { label: "Manual escalation required", value: null, tone: "critical" as const },
    { label: "Successful conversion (follows)", value: null, tone: "default" as const },
  ];

  return (
    <NovaCard className="spotlight-border h-[320px]" contentClassName="flex h-full flex-col p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-base font-medium text-foreground flex items-center gap-2">
            <MessageCircle aria-hidden="true" /> Auto-Responder Efficacy
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">Appears once reply outcomes are synced.</p>
        </div>
      </div>

      <div className="flex flex-1 flex-col justify-center gap-5 pb-4">
         {rows.map((row) => (
           <div key={row.label}>
             <div className="flex justify-between text-xs font-medium mb-1.5">
               <span className="flex items-center gap-1.5 text-muted-foreground">
                 {row.icon ? <Bot aria-hidden="true" /> : null}
                 {row.label}
               </span>
               <span className="text-muted-foreground">No sample</span>
             </div>
             <Progress value={0} tone={row.tone} />
           </div>
         ))}
      </div>

      <Separator />
      <div className="pt-3 text-center text-xs text-muted-foreground">
         SOURCE · reply outcome events required. No estimated time-saved value is shown until usage is measured.
      </div>
    </NovaCard>
  );
}
