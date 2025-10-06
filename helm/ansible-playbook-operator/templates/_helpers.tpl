{{- define "ansible-playbook-operator.fullname" -}}
{{- if .Chart.Name -}}{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}{{- else -}}{{ .Release.Name }}{{- end -}}
{{- end -}}

{{- define "ansible-playbook-operator.serviceAccountName" -}}
{{- if .Values.operator.serviceAccount.name -}}
{{- .Values.operator.serviceAccount.name -}}
{{- else -}}
{{- include "ansible-playbook-operator.fullname" . -}}
{{- end -}}
{{- end -}}

{{- define "ansible-playbook-operator.executorServiceAccountName" -}}
{{- if .Values.executorDefaults.serviceAccount.name -}}
{{- .Values.executorDefaults.serviceAccount.name -}}
{{- else -}}
{{- printf "%s-executor" (include "ansible-playbook-operator.fullname" .) -}}
{{- end -}}
{{- end -}}
