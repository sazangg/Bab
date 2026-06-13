import { LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * The one destructive-confirm dialog for the app: shows an impact preview (loading /
 * error+retry / content) and gates the confirm button until the impact has loaded.
 * Canonicalizes the pattern implemented 3+ ways today (and replaces `window.confirm`
 * in Guardrails). The caller renders the resolved impact via `children`.
 */
export function ImpactConfirmationDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  isLoadingImpact = false,
  impactError = false,
  onRetryImpact,
  confirmLabel = "Confirm",
  confirmTone = "destructive",
  onConfirm,
  isConfirming = false,
  confirmDisabled = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
  isLoadingImpact?: boolean;
  impactError?: string | boolean;
  onRetryImpact?: () => void;
  confirmLabel?: string;
  confirmTone?: "destructive" | "default";
  onConfirm: () => void;
  isConfirming?: boolean;
  confirmDisabled?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description != null && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        <div className="min-h-16">
          {isLoadingImpact ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" />
              Checking impact…
            </div>
          ) : impactError ? (
            <div className="flex flex-col items-start gap-2 text-sm text-muted-foreground">
              <span>
                {typeof impactError === "string" ? impactError : "Could not load the impact."}
              </span>
              {onRetryImpact ? (
                <Button variant="outline" size="sm" onClick={onRetryImpact}>
                  Retry
                </Button>
              ) : null}
            </div>
          ) : (
            children
          )}
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button
            variant={confirmTone}
            onClick={onConfirm}
            disabled={confirmDisabled || isConfirming || isLoadingImpact || Boolean(impactError)}
          >
            {isConfirming ? (
              <>
                <LoaderCircle className="size-4 animate-spin" data-icon="inline-start" />
                Working…
              </>
            ) : (
              confirmLabel
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
