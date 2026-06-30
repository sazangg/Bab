export function projectKeyCreationBlocker({
  projectIsActive,
  secretDeliveryDisabled,
  effectiveAccessUsable,
}: {
  projectIsActive: boolean;
  secretDeliveryDisabled: boolean;
  effectiveAccessUsable?: boolean;
}) {
  if (!projectIsActive) {
    return "Key creation is disabled because this project is archived.";
  }
  if (secretDeliveryDisabled) {
    return "Key creation is disabled because plaintext secret delivery is turned off in organization settings.";
  }
  if (effectiveAccessUsable === false) {
    return "Key creation is disabled until this project has usable effective access.";
  }
  return null;
}
