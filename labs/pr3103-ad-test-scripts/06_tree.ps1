$ErrorActionPreference = 'Stop'
$root = 'DC=ad,DC=example,DC=org'
$pw = ConvertTo-SecureString 'gns3test' -AsPlainText -Force
$svc = ConvertTo-SecureString 'svcldap123' -AsPlainText -Force

if (-not (Get-ADOrganizationalUnit -Filter 'Name -eq "gns3"' -SearchBase $root -SearchScope OneLevel -ErrorAction SilentlyContinue)) {
  New-ADOrganizationalUnit -Name 'gns3' -Path $root | Out-Null
  New-ADOrganizationalUnit -Name 'people' -Path "OU=gns3,$root" | Out-Null
  New-ADOrganizationalUnit -Name 'groups' -Path "OU=gns3,$root" | Out-Null
  "OUs created"
} else { "OUs already exist" }

function New-U ($u, $sn, $mail) {
  if (-not (Get-ADUser -Filter "SamAccountName -eq '$u'" -ErrorAction SilentlyContinue)) {
    New-ADUser -Name $u -SamAccountName $u -Path "OU=people,OU=gns3,$root" -GivenName $u -Surname $sn -DisplayName "$u $sn" -EmailAddress $mail -AccountPassword $pw -Enabled $true -PasswordNeverExpires $true | Out-Null
    "user $u created"
  } else { "user $u exists" }
}
New-U 'alice' 'Newleaf' 'alice@ad.example.org'
New-U 'bob'   'Admin'   'bob@ad.example.org'
New-U 'carol' 'Multi'   'carol@ad.example.org'
New-U 'dave'  'Tester'  'dave@ad.example.org'
New-U 'erin'  'Local'   'erin@ad.example.org'
New-U 'frank' 'Super'   'frank@ad.example.org'
if (-not (Get-ADUser -Filter "SamAccountName -eq 'svc-gns3'" -ErrorAction SilentlyContinue)) {
  New-ADUser -Name 'svc-gns3' -SamAccountName 'svc-gns3' -Path "OU=people,OU=gns3,$root" -DisplayName 'GNS3 Service Account' -AccountPassword $svc -Enabled $true -PasswordNeverExpires $true | Out-Null
  "user svc-gns3 created"
} else { "user svc-gns3 exists" }

foreach ($g in 'all-staff','gns3-superadmins','gns3-admins','gns3-testers') {
  if (-not (Get-ADGroup -Filter "Name -eq '$g'" -ErrorAction SilentlyContinue)) {
    New-ADGroup -Name $g -GroupScope Global -GroupCategory Security -Path "OU=groups,OU=gns3,$root" | Out-Null
    "group $g created"
  } else { "group $g exists" }
}
Add-ADGroupMember 'all-staff' 'alice' -ErrorAction SilentlyContinue
Add-ADGroupMember 'gns3-superadmins' 'frank' -ErrorAction SilentlyContinue
Add-ADGroupMember 'gns3-admins' 'bob','carol','erin' -ErrorAction SilentlyContinue
Add-ADGroupMember 'gns3-testers' 'carol','dave' -ErrorAction SilentlyContinue

"== user count: $((Get-ADUser -Filter * -SearchBase "OU=people,OU=gns3,$root").Count)"
"== group members:"
foreach ($g in 'all-staff','gns3-superadmins','gns3-admins','gns3-testers') {
  $m = (Get-ADGroupMember $g | ForEach-Object SamAccountName) -join ','
  "  $g : $m"
}
"== carol DN: $((Get-ADUser carol).DistinguishedName)"
"== svc DN:   $((Get-ADUser svc-gns3).DistinguishedName)"
"TREE_OK"
