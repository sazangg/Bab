import { FolderKanban } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useListProjectsApiV1ProjectsGet } from "@/shared/api/generated/projects/projects";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";

export function ProjectsPage() {
  const navigate = useNavigate();
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];

  return (
    <>
      <PageHeader
        title="Projects"
        description="Projects are created inside teams and receive allocations from their team."
        actions={
          <Button onClick={() => navigate("/teams")}>
            <FolderKanban />
            Manage teams
          </Button>
        }
      />

      {!projectsQuery.isPending && projects.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title="No projects yet"
          description="Create a team first, then add projects inside it."
          action={
            <Button onClick={() => navigate("/teams")}>
              <FolderKanban />
              Manage teams
            </Button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Team</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {projects.map((project) => (
                <TableRow
                  key={project.id}
                  className="cursor-pointer"
                  onClick={() => navigate(`/projects/${project.id}`)}
                >
                  <TableCell className="font-medium">{project.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {teams.find((team) => team.id === project.team_id)?.name ?? "-"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {project.description || "—"}
                  </TableCell>
                  <TableCell>
                    <StatusBadge variant={project.is_active ? "active" : "inactive"}>
                      {project.is_active ? "Active" : "Inactive"}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(project.created_at).toLocaleDateString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}
