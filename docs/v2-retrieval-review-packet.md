# Independent retrieval review packet

This packet prepares a human source review of a developer-selected pool. The reviewer grades how useful each source item is for migrating its named workflow. Original developer grades and retrieval ranks are omitted. The selection process remains a study limitation.

Review the full linked source, then assign 0 for irrelevant, 1 for supporting, 2 for relevant, or 3 for essential. Add a short reason for each judgment. Record your reviewer name and date. Zero-grade items remain in the review record and are excluded from the positive relevance set used by the existing evaluator.

The migration scope is Redmine 4.2.10 issue creation, visibility-aware reading, and issue status updates with audit effects. Use public source and the declared workflow requirements. Final verification observations are excluded from this review.

Source commit 9118c6dcb4ffe203f7029eb89523cd8a56b85cde.

Reviewer ____________________

Date ____________________

| Item | Workflow | Full source | Grade | Reason |
| --- | --- | --- | --- | --- |
| R01 | read | [app/controllers/application_controller.rb / authorize](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/controllers/application_controller.rb:302) | Pending | |
| R02 | read | [app/controllers/application_controller.rb / find_current_user](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/controllers/application_controller.rb:107) | Pending | |
| R03 | read | [app/controllers/application_controller.rb / find_issue](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/controllers/application_controller.rb:378) | Pending | |
| R04 | read | [app/controllers/issues_controller.rb / show](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/controllers/issues_controller.rb:89) | Pending | |
| R05 | read | [app/models/issue.rb / visible?](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue.rb:161) | Pending | |
| R06 | read | [app/models/issue.rb / visible_condition](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue.rb:126) | Pending | |
| R07 | read | [app/models/issue.rb / visible_journals_with_index](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue.rb:906) | Pending | |
| R08 | read | [app/views/issues/show.api.rsb / show.api.rsb](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/views/issues/show.api.rsb:1) | Pending | |
| R09 | create | [app/controllers/application_controller.rb / find_current_user](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/controllers/application_controller.rb:107) | Pending | |
| R10 | create | [app/controllers/issues_controller.rb / build_new_issue_from_params](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/controllers/issues_controller.rb:549) | Pending | |
| R11 | create | [app/controllers/issues_controller.rb / create](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/controllers/issues_controller.rb:136) | Pending | |
| R12 | create | [app/models/issue.rb / create_journal](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue.rb:1995) | Pending | |
| R13 | create | [app/models/issue.rb / default_assign](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue.rb:1935) | Pending | |
| R14 | create | [app/models/issue.rb / safe_attributes=](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue.rb:550) | Pending | |
| R15 | create | [app/models/issue.rb / validate_issue](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue.rb:748) | Pending | |
| R16 | create | [app/models/issue.rb / validate_permissions](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue.rb:836) | Pending | |
| R17 | create | [app/views/issues/show.api.rsb / show.api.rsb](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/views/issues/show.api.rsb:1) | Pending | |
| R18 | update | [app/controllers/application_controller.rb / authorize](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/controllers/application_controller.rb:302) | Pending | |
| R19 | update | [app/controllers/application_controller.rb / find_current_user](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/controllers/application_controller.rb:107) | Pending | |
| R20 | update | [app/controllers/issues_controller.rb / save_issue_with_child_records](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/controllers/issues_controller.rb:617) | Pending | |
| R21 | update | [app/controllers/issues_controller.rb / update](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/controllers/issues_controller.rb:183) | Pending | |
| R22 | update | [app/controllers/issues_controller.rb / update_issue_from_params](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/controllers/issues_controller.rb:519) | Pending | |
| R23 | update | [app/models/issue.rb / create_journal](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue.rb:1995) | Pending | |
| R24 | update | [app/models/issue.rb / init_journal](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue.rb:863) | Pending | |
| R25 | update | [app/models/issue.rb / new_statuses_allowed_to](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue.rb:1049) | Pending | |
| R26 | update | [app/models/issue.rb / safe_attributes=](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue.rb:550) | Pending | |
| R27 | update | [app/models/issue_status.rb / new_statuses_allowed_to](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/issue_status.rb:57) | Pending | |
| R28 | update | [app/models/journal.rb / save](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/journal.rb:97) | Pending | |
| R29 | update | [app/models/journal.rb / start](C:/Legacy_Lift/.legacylift/repositories/9118c6dcb4ffe203f7029eb89523cd8a56b85cde/app/models/journal.rb:202) | Pending | |

## Review boundaries

The current pool contains 29 workflow-item judgments. It covers selected symbols on one pinned repository. It does not establish retrieval quality over arbitrary repositories or complete recall over all relevant source. A completed independent review and scoring rerun are still pending.
