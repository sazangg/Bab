export const NO_SCOPE = "__none__";

export function scopedGrantError(
  teamId: string,
  teamRole: string,
  projectId: string,
  projectRole: string,
) {
  if (projectId !== NO_SCOPE && projectRole === NO_SCOPE) {
    return "Choose a project role before submitting.";
  }
  if (teamId !== NO_SCOPE && projectId === NO_SCOPE && teamRole === NO_SCOPE) {
    return "Choose a team role before submitting.";
  }
  return null;
}
