 # AIOS Agent Execution Pipeline + Review Center  Design

 2026-07-15

 ## Context

 ExecutionTaskDraft  (Gate 1)  creates confirmed `ExecutionTask`  but nothing
 happens afterwards.  `TaskStatus`  already defines  `QUEUED`  through  `APPLIED`
 and  `BaseAgent`  already has  `execute()`,  but these two parts of the system
 have never been wired together.

 This  module  bridges  that  gap  by  building  the  execution  pipeline  that
 dispatches  confirmed  Tasks  to  the  right  Agent,  runs  it  in  an  isolated
 git  worktree,  collects  Changes,  and  presents  them  to  the  user  for  the
 second  confirmation  (Gate  2)  before  any  change  touches  a  real  project.

 ## Design decisions

 ###  Isolated  worktrees,  not  containers

 Docker  containers  add  significant  complexity  before  we  have  a  single
 working  end-to-end  flow.  Git  worktrees  give  us  filesystem  isolation  at
 near-zero  cost  and  make  diff/cherry-pick  trivial.  We  add  a  container
 adapter  interface  so  the  isolation  strategy  is  swappable  later  without
 touching  the  Agent  runner  or  Review  Center.

 ###  PULL  dispatch,  not  PUSH

 Nothing  fires  automatically  when  a  Task  is  confirmed.  The  user  must
 explicitly  request  "execute  task  X"  (or  the  mobile  UI  provides  a
 "Start  Execution"  button).  This  keeps  the  safety  model  consistent:
 the  user  triggers  Gate  1  (confirm  task  scope)  and  Gate  2  (review
 changes)  explicitly.

 ###  Agent  dispatch  by  capabilities

 `ExecutionTask.requested_capabilities`  is  already  a  `list[str]`.  We  map
 those  to  `BaseAgent.capabilities`  via  the  `AgentRegistry`.  If  no  agent
 matches,  the  dispatch  fails  with  a  clear  error  (user  can  edit  the
 Task's  requested  capabilities  and  retry).  If  multiple  match,  we  pick
 the  first  that  matches  the  most  capabilities  (future:  configurable
 priority).

 ###  Review  Center  is  the  Gate  2  UI

 After  the  Agent  finishes,  the  Task  enters  `AWAITING_CHANGE_REVIEW`.
 The  review  centre  shows:
 -  Source  task  (what  the  user  asked  for)
 -  Agent  that  ran
 -  Every  Change  with  its  diff  (unified  format,  syntax-highlighted)
 -  Test  results  summary  (if  available)
 -  Accept/Reject  per  change  or  bulk

 Only  after  user  approval  do  we  enter  `APPLYING  ->  APPLIED`.

 ##  New  ORM  models

 ###  ExecutionChange  (New  table:  `execution_changes`)

 Stores  the  result  of  an  Agent's  `execute()`  call.  Each  `Change`
 from  `AgentResult`  becomes  one  row.  Tied  to  a  `run_id`.

 -  `id`  UUID  PK
 -  `run_id`  UUID  FK  ->  execution_runs.id
 -  `path`  Text  NotNull
 -  `action`  varchar(10)  NotNull  (create/modify/delete)
 -  `description`  Text  NotNull
 -  `content_before`  Text  Nullable
 -  `content_after`  Text  Nullable
 -  `diff`  Text  Nullable  (unified  diff)
 -  `status`  varchar(20)  NotNull  (pending/approved/rejected/applied/failed)
 -  `error_message`  Text  Nullable
 -  `approved_at`  timestamptz  Nullable

 ###  ExecutionRun  (New  table:  `execution_runs`)

 One  run  per  dispatch.  A  Task  can  have  multiple  runs  (if  user  rejects
 changes  and  restarts  with  different  parameters).

 -  `id`  UUID  PK
 -  `task_id`  UUID  FK  ->  execution_tasks.id
 -  `agent_name`  varchar(64)  NotNull
 -  `isolation_type`  varchar(32)  NotNull  (git_worktree)
 -  `isolation_path`  Text  NotNull  (worktree  location)
 -  `state`  varchar(32)  NotNull  (queued/running/completed/failed)
 -  `summary`  Text  Nullable
 -  `test_results`  jsonb  Nullable
 -  `started_at`  timestamptz  Nullable
 -  `completed_at`  timestamptz  Nullable

 ###  TaskStatus  transitions

 CONFIRMED  ->  QUEUED  (user  clicks  "Start  Execution")
 QUEUED  ->  RUNNING_IN_ISOLATION  (dispatch  begins)
 RUNNING_IN_ISOLATION  ->  AWAITING_CHANGE_REVIEW  (agent  done,  changes  ready)
 AWAITING_CHANGE_REVIEW  ->  CHANGE_APPROVED  (user  accepts)
 AWAITING_CHANGE_REVIEW  ->  CHANGE_REJECTED  (user  rejects  ->  back  to  CONFIRMED  for  retry)
 CHANGE_APPROVED  ->  APPLYING  (apply  begins)
 APPLYING  ->  APPLIED  (apply  succeeded)
 APPLYING  ->  FAILED  (apply  failed)
 RUNNING_IN_ISOLATION  ->  FAILED  (agent  crashed/timed  out)

 ##  Module  structure

 ```
 backend/app/
  execution/
   base.py         (unchanged)
   policy.py       (unchanged)
   projector.py    (unchanged)
   service.py      (unchanged)
   dispatcher.py   (NEW:  Agent  selection  +  orchestration)
   isolation.py    (NEW:  worktree  create/cleanup)
   runner.py       (NEW:  execute  agent  in  isolation)
   review.py       (NEW:  collect  changes,  serve  diff)
   apply.py        (NEW:  apply  approved  changes)
  models/
   execution.py    (amend:  add  ExecutionRun,  ExecutionChange)
  schemas/
   execution.py    (amend:  add  schemas  for  run,  change,  review)
  api/
   execution.py    (amend:  add  routes  for  dispatch,  review,  apply)
 alembic/versions/
   0008_create_execution_runs_changes.py  (NEW)
 ```

 ##  API  endpoints

 ###  Dispatch
 -  `POST  /api/v1/execution-tasks/{task_id}/dispatch`
   -  Body:  `{project_id:  UUID,  force_agent:  string?}`
   -  Response:  `ExecutionRunResponse`  +  task  status  ->  QUEUED/RUNNING_IN_ISOLATION
   -  Starts  the  Agent  execution  asynchronously

 ###  Run  status
 -  `GET  /api/v1/execution-runs/{run_id}`
   -  Response:  `ExecutionRunResponse`  with  current  state,  output  summary

 ###  Review
 -  `GET  /api/v1/execution-runs/{run_id}/changes`
   -  Response:  `list[ExecutionChangeResponse]`  with  full  diff
 -  `POST  /api/v1/execution-runs/{run_id}/changes/decision`
   -  Body:  `{decisions:  [{change_id,  decision:  approved|rejected}]}`
   -  Response:  updated  run  +  task  status

 ###  Apply
 -  `POST  /api/v1/execution-runs/{run_id}/apply`
   -  Applies  all  approved  changes  to  the  real  project
   -  Response:  task  status  ->  APPLIED

 ##  Safety  invariants

 1.  No  Agent  execution  without  a  confirmed  Task  (never  skip  Gate  1).
 2.  All  agent  disk  writes  go  into  an  isolated  worktree,  never  the  real  project.
 3.  Changes  are  presented  as  unified  diffs;  the  user  must  explicitly  approve  each  change  or  a  bulk  decision.
 4.  Apply  only  touches  files  listed  in  `task.allowed_paths`  and  rejects  any  file  outside  that  set.
 5.  The  system  never  auto-commits,  auto-pushes,  or  auto-deploys  (mirrors  `SYSTEM_GUARDRAILS`).
 6.  Agent  timeout:  hard  cap  at  10  minutes  (configurable).  On  timeout,  task  enters  FAILED  and  worktree  is  cleaned  up.

 ##  Swappable  interfaces

 -  `IsolationProvider`  protocol:  currently  `GitWorktreeProvider`  default.
   Swap  to  `DockerContainerProvider`  later  without  changing  runner/review/apply.
 -  `ChangeApplier`  protocol:  currently  `GitPatchApplier`  default.
   Swap  to  direct  file  copy  or  GitHub  PR  merge  later.
 -  Agent  dispatch  already  uses  `AgentRegistry.find_by_capability()`.
   Adding  a  priority/weight  system  later  just  needs  a  new  selector  impl.

 ##  Voice  flow  (future)

 The  execution  pipeline  is  API-driven;  voice  interaction  will  land  here
 once  the  text-based  mobile  UI  is  verified.  The  user  will  say  "start
 executing  task  X",  the  Cognitive  Engine  classifies  it,  and  the  dispatch
 endpoint  receives  the  same  API  call  as  the  text  path.

 ##  What's  NOT  in  this  module

 -  Real  Agent  implementations  (codex-stub  stays  a  stub;  real  Codex  /  Claude  Code  /  Git  Agent  /  Test  Agent  are  separate  plugins  later).
 -  Background  scheduler:  dispatch  is  user-triggered  via  REST  API.  Scheduled  execution  is  a  future  feature.
 -  Streaming  progress:  Agent  output  is  collected  as  a  batch  for  Gate  2  review.  Real-time  streaming  is  future.
 -  Multi-agent  orchestration:  one  Task  =  one  Agent  for  now.  Chaining  multiple  agents  is  future.
