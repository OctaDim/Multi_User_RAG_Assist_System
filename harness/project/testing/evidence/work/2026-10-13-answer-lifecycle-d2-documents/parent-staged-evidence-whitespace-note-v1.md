# Evidence bytes and whitespace

Raw native/test stdout and completed proof JSON may contain trailing whitespace or blank EOF lines. Preserve those evidence bytes and existing proof hashes. Stage source/config/tests and evidence through the explicit owned manifest; use source-only staged diff --check. Do not normalize historical evidence to satisfy a source formatting check. Transport research is excluded from this D2 commit and remains U7 work.
