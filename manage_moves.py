"""Inspect move requests; record success only AFTER the native Codex tool succeeds."""
import argparse
import json
import server

def complete(thread_id, project_id):
    with server.connect() as db:
        row=db.execute('SELECT value FROM metadata WHERE key=?',('chatAssignments',)).fetchone()
        assignments=json.loads(row[0]) if row else {}
        request=assignments.get(thread_id)
        if not request or request['codexProjectId'] != project_id or request['nativeStatus'] != 'pending':
            raise ValueError('No matching pending native move. Re-read the request before proceeding.')
        request.update(nativeStatus='complete',completedAt=server.now())
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('chatAssignments',json.dumps(assignments)))
    return request

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('list')
    done=commands.add_parser('complete')
    done.add_argument('--thread-id',required=True)
    done.add_argument('--project-id',required=True)
    args=parser.parse_args()
    server.initialize()
    if args.command=='list':
        print(json.dumps([r for r in (server.metadata('chatAssignments') or {}).values() if r['nativeStatus']=='pending'],indent=2))
    else:
        print(json.dumps(complete(args.thread_id,args.project_id),indent=2))
