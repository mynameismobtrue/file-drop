# Production Gate

`STATE=PRE_PRODUCTION` até TODOS os itens abaixo serem comprovados:

- [ ] regression suite PASS no GitHub Actions
- [ ] pelo menos um discovery provider live autenticado
- [ ] execução manual real concluída
- [ ] schema real validado
- [ ] inspeção de serialização confirma ausência de secrets/session tokens
- [ ] 12/12 queries concluídas no discovery provider ativo
- [ ] `VALID_OFFERS` revisadas
- [ ] `REJECTED_OFFERS` revisadas
- [ ] `NON_VALIDATABLE_OFFERS` revisadas
- [ ] pelo menos um candidato revalidado quando houver candidato disponível
- [ ] histórico persistido corretamente
- [ ] ciclo incompleto testado sem sobrescrever snapshot completo
- [ ] privacidade do repositório/snapshots revisada
- [ ] aprovação explícita do usuário para ligar schedule

Somente depois disso configurar `FLIGHT_BRIDGE_PRODUCTION_APPROVED=true` e alterar o estado de forma explícita. Não existe promoção automática baseada apenas em testes unitários.
