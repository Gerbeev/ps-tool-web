# Process Scheduler — `IDbAccessService` WCF Endpoint Specification

Spec for building, from scratch, a connector that pulls job/topology status from the Process
Scheduler WCF service.

> **External dependency — read this first.** A pure-Python service **cannot** talk to this
> endpoint (see §1). A .NET component that speaks `netTcpBinding` is mandatory — either the
> existing `modules/TopoBrowse.Bridge` project (console helper invoked as a subprocess, JSON
> on stdout) copied/added into the new project by hand, or a new .NET component built from
> §1–§5 of this spec. Without one of these two, there is no way to reach Process Scheduler at
> all — this is not an optional integration detail, it's a hard protocol requirement.

## 1. Transport

- Protocol: WCF `netTcpBinding`, binary TCP wire format (not HTTP/SOAP-text).
- Security: `SecurityMode.None` — no transport or message security, no credentials, no TLS.
- Endpoint address pattern: `net.tcp://<host>:<port>/<service_name>`
  - `service_name` default: `DbAccessService`
- No Python implementation exists for netTcpBinding's binary framing — a .NET client is required
  (pure-Python HTTP clients won't work against this transport). This .NET client must be added to
  the project manually (vendored source, or a locally built/pre-built executable) — it is an
  external dependency this spec alone does not provide the binary for.

### 1.1 Binding configuration (client side)

```csharp
var binding = new NetTcpBinding(SecurityMode.None)
{
    MaxReceivedMessageSize = maxMessageMb * 1024L * 1024L,   // default 200 MB
    ReaderQuotas = { MaxStringContentLength = int.MaxValue },
    CloseTimeout = timeout,     // default 60s
    OpenTimeout = timeout,
    SendTimeout = timeout,
    ReceiveTimeout = timeout,
};
var endpoint = new EndpointAddress($"net.tcp://{baseAddress}/{serviceName}");
var factory = new ChannelFactory<IDbAccessService>(binding, endpoint);
var channel = factory.CreateChannel();
((IClientChannel)channel).Open();
```

NuGet package required (client-only, no internal assembly reference needed):
`System.ServiceModel.NetTcp` version `8.1.2`, target framework `net9.0`.

## 2. Real endpoints (current `configs/environments.yaml`)

| Code | Environment | Address (`host:port`) |
|---|---|---|
| BB | Main Prod | `np12971565bbp1.ubscloud-prod.msad.ubs.net:9001` |
| PA | Secondary Prod | `np3e791565pap2.ubscloud-prod.msad.ubs.net:9001` |
| PB | to be decommissioned | `np3e791565pbp1.ubscloud-prod.msad.ubs.net:9001` |
| PY | Pillar 2 Prod | `np3e791565pyp1.ubscloud-prod.msad.ubs.net:9001` |
| P1 | Cloud Data Sourcing Prod | `np3e791565p1p1.ubscloud-prod.msad.ubs.net:9001` |
| UX | Main UAT Primary | `np405216831uxp1.ubscloud-prod.msad.ubs.net:9001` |
| UW | Main UAT Secondary | `np405216831uwp1.ubscloud-prod.msad.ubs.net:9001` |
| UZ | Interactive UAT | `np405216831uzp2.ubscloud-prod.msad.ubs.net:9001` |
| U1 | Cloud Data Sourcing UAT | `npb14716831u1p1.ubscloud-prod.msad.ubs.net:9001` |
| U5 | UAT | `npb14716831u5p1.ubscloud-prod.msad.ubs.net:9001` |
| XY | PIE | `nd29201564xyp1.ubscloud-prod.msad.ubs.net:9001` |
| XZ | PIE | `nd29201564xzp1.ubscloud-prod.msad.ubs.net:9001` |
| DV | PSO env DEV | `nd29201564dvp1.ubscloud-prod.msad.ubs.net:9001` |
| DZ | Quantum env DEV | `nd29201564dzp1.ubscloud-prod.msad.ubs.net:9001` |

All ports are `9001`. Full endpoint example:
`net.tcp://np12971565bbp1.ubscloud-prod.msad.ubs.net:9001/DbAccessService`.

Defaults (`configs/environments.yaml` → `defaults.wcf`): `service_name: DbAccessService`, `timeout_seconds: 60`, `max_received_message_mb: 200`.

## 3. Service contract

```csharp
namespace RAIT.ProcessScheduler.Common.Interfaces
{
    [ServiceContract]
    public interface IDbAccessService
    {
        [OperationContract]
        IEnumerable<string> GetContextNames();

        [OperationContract]
        IEnumerable<ContextDto> GetContexts(IEnumerable<string> contextNames);
    }
}
```

- The client-side mirror interface must be named exactly `IDbAccessService` (any CLR namespace is
  fine) with identical operation and parameter names — the SOAP action strings are derived from
  these names and must match what the server dispatches.
- Only two operations exist:
  - `GetContextNames()` — lists every **running topology instance** name (a "context" = one
    running instance of a topology, e.g. `EOD_20241001`).
  - `GetContexts(IEnumerable<string> contextNames)` — full box/command status for the named
    instance(s).
- No "describe single job" operation exists server-side — job detail is extracted by filtering
  the `GetContexts` result for one job by name (see §5).

## 4. Data contracts (DTOs)

WCF `DataContractSerializer` matches by `(Name, Namespace)`, not CLR assembly identity, and
silently drops wire fields a client-side type doesn't declare (forward-compatible). Default
`[DataContract]` namespace (no override) = `http://schemas.datacontract.org/2004/07/` + the C#
namespace, so the client mirror must use the **exact same namespace string**:
`RAIT.ProcessScheduler.Common.Dtos` / `RAIT.ProcessScheduler.Common.Enums`.

```csharp
namespace RAIT.ProcessScheduler.Common.Dtos
{
    [DataContract]
    public abstract class JobBaseDto : IExtensibleDataObject   // captures undeclared wire fields
    {
        [DataMember] public string? Context { get; set; }
        [DataMember] public string? Name { get; set; }
        [DataMember] public string? Box { get; set; }
        [DataMember] public JobStatus Status { get; set; }
        [DataMember] public JobType JobType { get; set; }
        [DataMember] public DateTime LastStartTime { get; set; }
        [DataMember] public DateTime LastFinishTime { get; set; }
        [DataMember] public string? StartAtTime { get; set; }
        [DataMember] public string? Schedule { get; set; }
        public ExtensionDataObject? ExtensionData { get; set; }
    }

    [DataContract] public class BoxJobDto : JobBaseDto { }

    [DataContract]
    public class CommandJobDto : JobBaseDto
    {
        [DataMember] public string? Machine { get; set; }
        [DataMember] public string? Command { get; set; }
    }

    [DataContract]
    public class TopologyDto
    {
        [DataMember] public string? Name { get; set; }
        [DataMember] public int RevisionNumber { get; set; }
        [DataMember] public BoxJobDto[]? Boxes { get; set; }
        [DataMember] public CommandJobDto[]? Commands { get; set; }
    }

    [DataContract]
    public class ContextDto
    {
        [DataMember] public TopologyDto? TopologyDto { get; set; }
        [DataMember] public DateTime SaveSnapshotTime { get; set; }
    }
}

namespace RAIT.ProcessScheduler.Common.Enums
{
    public enum JobStatus { Inactive, Activated, Starting, Running, Success, Terminated, Failed, Waiting, Cancelled, OnIce, OnHold }
    public enum JobType { Box, Command, K8sCronJob, WebApi }
}
```

- Plain (undecorated) enums serialize by member name — matching is name-based, order doesn't matter.
- `IExtensibleDataObject` on `JobBaseDto` lets the connector recover fields the server sends that
  aren't explicitly declared above. **This is important, not optional** — confirmed live wire
  fields not in the DTOs above include:
  - `ConditionExpression.Conditions.ConditionDto` — the job's **dependency list**. When a job
    depends on a single upstream job this is one `ConditionDto` object; when it depends on
    **multiple** upstream jobs it becomes a **list** of `ConditionDto` objects (same "repeated
    element name → array" rule as the raw-dump parsing in §5 step 7). Each entry has:
    - `ConditionType` — e.g. `Success` (same meaning as AutoSys `s(JOB)`).
    - `DependencyJobName` — the upstream job name this job depends on. Confirmed to reference
      **either** a command job **or** a box (e.g. `..._Box`) — when resolving it, search both
      `TopologyDto.Boxes` and `TopologyDto.Commands` by name, same as job lookup in §5 step 6.
  - `Description`, `Owner` — free-text / owning account, `null` when unset.
  - `StartAtTimeForce` — bool.
  - `EnvironmentVariables` — `null` when unset, presumably a map when set.
  - `ResourceName` — logical resource/queue the job runs under (e.g. `DataPlatform`).
  - `StdErrorFile`, `StdOutputFile` — log file paths (same role as AutoSys `std_err_file`/`std_out_file`).
  - `UseParticularAgent` — bool.
  - `Weight` — integer, scheduling weight/priority.

  None of these are declared on `JobBaseDto`/`BoxJobDto`/`CommandJobDto` above — they only appear
  through the raw dump described in §5 step 7. Do not skip that step if dependencies or these
  extra fields are needed.

## 5. How to get job/topology info

1. New .NET project (`net9.0`), package `System.ServiceModel.NetTcp` (`8.1.2`).
2. Declare `IDbAccessService` + DTOs/enums exactly as in §3–§4 (name/namespace-exact).
3. Build the `netTcpBinding` `ChannelFactory<IDbAccessService>` per §1.1, open the channel.
4. Call `GetContextNames()` to list running topology instances (contexts), e.g. `EOD_20241001`.
5. Call `GetContexts(names)` with one or more context names to get full box/command status for
   those instances. `DateTime.MinValue` on `LastStartTime`/`LastFinishTime` means the job never ran.
6. To describe a single job: call `GetContexts` for its context, then search `TopologyDto.Boxes`
   then `TopologyDto.Commands` for a case-insensitive name match (no separate "describe" operation
   exists server-side).
7. **To get job dependencies** (and any other server field the DTOs above don't declare): re-serialize
   the matched `BoxJobDto`/`CommandJobDto` with the same `DataContractSerializer` used to deserialize
   it (its `IExtensibleDataObject.ExtensionData` round-trips automatically), then parse the resulting
   XML into a plain name→value tree (repeated element names → arrays, leaf elements → strings, empty
   elements → `null`). Look for `ConditionExpression.Conditions.ConditionDto` in that tree — each
   entry has `ConditionType` (e.g. `Success`) and `DependencyJobName` (the upstream job name).
   Single dependency (one `ConditionDto` object):
   ```
   ConditionExpression:
     Conditions:
       ConditionDto:
         ConditionType: Success
         DependencyJobName: IB_CT_CVA_1109_U5_Enrichment_TemplateSync
   ```
   Multiple dependencies (`ConditionDto` becomes a **list** — code must handle both shapes, not
   assume a single object):
   ```
   ConditionExpression:
     Conditions:
       ConditionDto:
         - ConditionType: Success
           DependencyJobName: IB_CT_CVA_1109_U5_Job_A
         - ConditionType: Success
           DependencyJobName: IB_CT_CVA_1109_U5_Job_B
   ```
   This raw dump is the **only** way to see dependencies or any other undeclared wire field
   (`Description`, `Owner`, `StartAtTimeForce`, `EnvironmentVariables`, `ResourceName`,
   `StdErrorFile`, `StdOutputFile`, `UseParticularAgent`, `Weight`, ...); the declared DTO fields
   never carry them.
8. No credentials, TLS, or headers are involved — only TCP reachability to `<host>:9001` matters.

## 6. Error semantics

| Situation | Behavior |
|---|---|
| Endpoint unreachable | .NET `EndpointNotFoundException` |
| Call exceeds timeout | `TimeoutException` |
| Any other WCF fault | `CommunicationException` |
