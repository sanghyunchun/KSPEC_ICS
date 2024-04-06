

case "$1" in
	ics)
	   (cd KSPEC_client; python KSPECRUN.py)
	   ;;

	tcs)
	   (cd KSPEC_Server/TCS; python TCS_server.py)
	   ;;

	gfa)
	   (cd KSPEC_Server/GFA; python GFA_server.py)
	   ;;

	mtl)
	   (cd KSPEC_Server/MTL; python MTL_server.py)
	   ;;
esac
