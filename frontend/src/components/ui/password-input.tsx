import { Eye, EyeOff } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * A password Input paired with a show/hide toggle. Owns its own reveal state and forwards
 * the ref + all Input props (so it drops straight into react-hook-form's register()).
 */
export const PasswordInput = React.forwardRef<HTMLInputElement, React.ComponentProps<typeof Input>>(
  function PasswordInput(props, ref) {
    const [show, setShow] = React.useState(false);
    return (
      <div className="flex gap-2">
        <Input ref={ref} {...props} type={show ? "text" : "password"} />
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={show ? "Hide secret" : "Show secret"}
          onClick={() => setShow((value) => !value)}
        >
          {show ? <EyeOff /> : <Eye />}
        </Button>
      </div>
    );
  },
);
