 方案一：Git over SSH（推荐）
  服务器上（一次性操作）：
  git init --bare ~/startupv2.git                                                                  
  
  本地添加 remote：
  # IPv6 地址要用方括号包住
  git remote add server ssh://user@[2001:db8::1]/~/startupv2.git

  # 推送
  git push server master

  之后每次部署就一条命令：
  git push server master

  如果服务器上还需要自动部署（推送后自动 checkout 到工作目录），在服务器的
  ~/startupv2.git/hooks/post-receive 里加：
  #!/bin/bash
  git --work-tree=/home/user/project --git-dir=/home/user/startupv2.git checkout -f master
  然后 chmod +x post-receive。


git --work-tree=/root/StartUp --git-dir=/root/startup.git checkout -f master

cat /etc/supervisor/conf.d/*.conf
 supervisorctl reread
  supervisorctl update
  supervisorctl restart 你的程序名

  /root/py_venv/venv/bin/pip install -r /root/StartUp/requirements.txt

  echo 'supervisorctl restart startups' >>                 ~/startup.git/hooks/post-receive