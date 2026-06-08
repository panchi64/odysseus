import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import { createStore, produce } from "solid-js/store";
import { useNavigate } from "@solidjs/router";
import {
  Button,
  EmptyState,
  InfoHint,
  InstrumentBand,
  ListRow,
  ListToolbar,
  LoadingText,
  Menu,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Tabs,
  Text,
  Tooltip,
  confirm,
  toast,
} from "~/ui";
import { createListView } from "~/lib/list";
import { relativeTime } from "~/lib/format";
import { useSkills } from "../data";
import { skillStatusFlag, type Skill, type SkillStatus } from "../model";
import { TestSkillModal } from "../components/TestSkillModal";

const STATUS_TABS = [
  { value: "all", label: "ALL" },
  { value: "published", label: "PUBLISHED" },
  { value: "draft", label: "DRAFT" },
  { value: "auto", label: "AUTO" },
];

export function SkillsDirectoryScreen(): JSX.Element {
  const navigate = useNavigate();
  const skillsResource = useSkills();
  const [statusFilter, setStatusFilter] = createSignal("all");
  const [testSkill, setTestSkill] = createSignal<Skill | null>(null);

  // Mutable store seeded once from the resource (same pattern as tokens feature)
  const [skills, setSkills] = createStore<Skill[]>([]);
  let seeded = false;

  function seed(list: Skill[]) {
    if (!seeded) {
      seeded = true;
      setSkills(list.map((s) => ({ ...s })));
    }
  }

  // ── delete ──────────────────────────────────────────────────────────────

  async function handleDelete(skill: Skill) {
    if (
      !(await confirm({
        title: `Delete "${skill.name}"?`,
        detail:
          "This skill will be permanently removed and cannot be recovered.",
        confirmLabel: "DELETE",
        tone: "alert",
      }))
    )
      return;

    const removed = { ...skill };
    setSkills((list) => list.filter((s) => s.id !== skill.id));

    toast.success(`Deleted "${skill.name}"`, {
      action: {
        label: "UNDO",
        onClick: () => setSkills((list) => [removed, ...list]),
      },
    });
  }

  // ── publish / unpublish ─────────────────────────────────────────────────

  function handlePublishToggle(skill: Skill) {
    if (skill.status === "auto") {
      toast.warn("Auto-generated skills cannot be published or unpublished.");
      return;
    }
    const nextStatus = skill.status === "published" ? "draft" : "published";
    setSkills(
      (s) => s.id === skill.id,
      produce((s) => {
        s.status = nextStatus;
      }),
    );
    toast.success(
      nextStatus === "published"
        ? `"${skill.name}" published.`
        : `"${skill.name}" unpublished — moved to draft.`,
    );
  }

  // ── derived ─────────────────────────────────────────────────────────────

  const allSkills = () => skills;
  const countOf = (s: SkillStatus) =>
    allSkills().filter((sk) => sk.status === s).length;
  const byStatus = () => {
    const f = statusFilter();
    if (f === "all") return allSkills().slice();
    return allSkills().filter((s) => s.status === f);
  };

  const view = createListView({
    source: byStatus,
    search: (s) => `${s.name} ${s.trigger} ${s.description}`,
    sorts: {
      recent: {
        label: "NEWEST",
        compare: (a, b) => a.updatedAt.localeCompare(b.updatedAt),
      },
      name: {
        label: "NAME",
        compare: (a, b) => a.name.localeCompare(b.name),
      },
    },
    initialSort: "recent",
    initialDir: "desc",
  });

  return (
    <Stack gap={6}>
      <PageHeader
        title="SKILLS"
        subtitle="Reusable procedures the assistant can invoke by trigger phrase."
        assetId="ODY-SKL-01.0"
        actions={
          <Tooltip label="Available in Phase 2">
            <Button variant="primary" leading="plus" disabled>
              NEW SKILL
            </Button>
          </Tooltip>
        }
      />

      <InstrumentBand
        items={[
          { label: "TOTAL", value: String(allSkills().length) },
          {
            label: "PUBLISHED",
            value: String(countOf("published")),
            tone: "nominal",
          },
          { label: "DRAFT", value: String(countOf("draft")), tone: "warn" },
          { label: "AUTO", value: String(countOf("auto")), tone: "info" },
        ]}
      />

      <Panel flush>
        <div class="flex items-center justify-between gap-3 border-b border-line pr-3">
          <Tabs
            items={STATUS_TABS}
            value={statusFilter()}
            onChange={setStatusFilter}
          />
          <Row align="center" gap={3}>
            <Row align="center" gap={1}>
              <Text variant="micro" tone="dim">
                DRAFT
              </Text>
              <InfoHint label="A draft is unpublished — the assistant won't invoke it. Publishing requires a name, a trigger phrase, and a non-empty body." />
            </Row>
            <Row align="center" gap={1}>
              <Text variant="micro" tone="dim">
                AUTO
              </Text>
              <InfoHint label="Auto-generated skills are synthesized by the system from your usage patterns. They can be edited or deleted, but not manually published or unpublished." />
            </Row>
          </Row>
        </div>

        <div class="border-b border-line p-3">
          <ListToolbar
            query={view.query()}
            onQueryChange={view.setQuery}
            placeholder="Search by name or trigger phrase…"
            sortKey={view.sortKey()}
            sortOptions={view.sortOptions}
            onSortChange={view.setSort}
            dir={view.dir()}
            onToggleDir={view.toggleDir}
            count={view.count()}
            total={view.total()}
          />
        </div>

        <Suspense
          fallback={
            <div class="p-4">
              <LoadingText />
            </div>
          }
        >
          {/* Seed the mutable store from the resource once loaded */}
          <Show when={skillsResource()} keyed>
            {(list) => {
              seed(list);
              return null;
            }}
          </Show>

          <Show
            when={view.items().length}
            fallback={
              <EmptyState
                icon="code"
                message="NO SKILLS"
                hint={
                  view.isFiltered()
                    ? "No skills match your search."
                    : "No skills match the current filter."
                }
              />
            }
          >
            <For each={view.items()}>
              {(skill) => (
                <ListRow
                  label={skill.name}
                  leading="code"
                  href={`/skills/${skill.id}`}
                  right={
                    <span class="flex shrink-0 items-center gap-3">
                      <Show when={skill.autoGenerated}>
                        <StatusFlag status="info">AUTO</StatusFlag>
                      </Show>
                      <StatusFlag status={skillStatusFlag[skill.status]}>
                        {skill.status.toUpperCase()}
                      </StatusFlag>
                      <Text variant="micro" tone="dim">
                        {relativeTime(skill.updatedAt)}
                      </Text>
                      {/* Stop row navigation when interacting with the menu. */}
                      <span
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                        }}
                      >
                        <Menu
                          trigger={
                            <span class="px-1 text-dim hover:text-bright">
                              <Text variant="micro">···</Text>
                            </span>
                          }
                          items={[
                            {
                              label: "EDIT",
                              icon: "edit",
                              onSelect: () => navigate(`/skills/${skill.id}`),
                            },
                            {
                              label: "TEST",
                              icon: "play",
                              onSelect: () => setTestSkill(skill),
                            },
                            {
                              label:
                                skill.status === "published"
                                  ? "UNPUBLISH"
                                  : "PUBLISH",
                              icon: "check",
                              onSelect: () => handlePublishToggle(skill),
                            },
                            {
                              label: "DELETE",
                              icon: "trash",
                              danger: true,
                              onSelect: () => void handleDelete(skill),
                            },
                          ]}
                        />
                      </span>
                    </span>
                  }
                />
              )}
            </For>
          </Show>
        </Suspense>
      </Panel>

      <TestSkillModal skill={testSkill()} onClose={() => setTestSkill(null)} />
    </Stack>
  );
}
