# auto_edit_client

Cliente Dart da API do motor (`auto-edit serve`), gerado de
[`auto_edit/openapi.yaml`](../../auto_edit/openapi.yaml). Usado pelo app
Flutter no desktop e no celular.

```dart
import 'package:auto_edit_client/auto_edit_client.dart';

final engine = AutoEditClient(EngineConfig.local());            // o motor desta máquina
// final engine = AutoEditClient(EngineConfig.parse('192.168.0.10', token: '...'));  // o de casa

if (!await engine.isCompatible()) { /* motor com contrato de outra major */ }
final library = await engine.api.listLibrary();

final job = await engine.api.resumeVideo('meu_video', const ResumeVideoRequest(fromStage: 'caption'));
await for (final e in engine.api.jobEvents(job.jobId)) {
  print('${e.type} ${e.line ?? e.stage ?? ''}');
}
```

- `lib/src/generated/` — **gerado**, não editar. Depois de mudar o spec:
  `python scripts/gen_dart_client.py` (na raiz do repo; com `dart` no PATH
  sai formatado). `--check` falha se estiver desatualizado (a CI roda).
- `lib/src/transport.dart` — HTTP, token, erros e o SSE com reconexão.
- `lib/src/sse.dart` — parser de Server-Sent Events.

Testes: `dart test` (o de integração sobe um `auto-edit serve` de verdade;
`AUTO_EDIT_BIN` aponta o executável, padrão `auto-edit` do PATH).
Só os de unidade: `dart test -x integration`.
