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
